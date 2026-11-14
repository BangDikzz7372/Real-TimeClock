"""Menambahkan widget jam, alarm native (lagu pilihan), suara bawaan, dan izin
ke proyek Android hasil `cap add android`."""
import math
import os
import struct
import wave

PKG = 'com.dikzz.realtimeclock'
MAIN = os.path.join('android', 'app', 'src', 'main')
JAVA = os.path.join(MAIN, 'java', *PKG.split('.'))


def tulis(path, isi):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(isi.replace('__PKG__', PKG))


# ======================= JAVA =======================

tulis(os.path.join(JAVA, 'MainActivity.java'), '''package __PKG__;

import android.os.Build;
import android.os.Bundle;
import android.view.WindowManager;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(AlarmPlugin.class);
        super.onCreate(savedInstanceState);
        // Agar layar alarm tampil di atas layar kunci
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
    }
}
''')

tulis(os.path.join(JAVA, 'AlarmScheduler.java'), '''package __PKG__;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import java.util.Calendar;
import java.util.Map;
import org.json.JSONException;
import org.json.JSONObject;

public class AlarmScheduler {
    static final String PREFS = "jam_alarms";

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static long nextTime(int h, int m) {
        Calendar c = Calendar.getInstance();
        c.set(Calendar.HOUR_OF_DAY, h);
        c.set(Calendar.MINUTE, m);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        if (c.getTimeInMillis() <= System.currentTimeMillis()) {
            c.add(Calendar.DAY_OF_YEAR, 1);
        }
        return c.getTimeInMillis();
    }

    static PendingIntent firePi(Context c, int id) {
        Intent i = new Intent(c, AlarmReceiver.class);
        i.setAction("__PKG__.ALARM");
        i.putExtra("id", id);
        return PendingIntent.getBroadcast(c, id, i,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    static void schedule(Context c, JSONObject a) throws JSONException {
        int id = a.getInt("id");
        long t = nextTime(a.getInt("h"), a.getInt("m"));
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        Intent show = new Intent(c, MainActivity.class);
        PendingIntent showPi = PendingIntent.getActivity(c, id, show,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        am.setAlarmClock(new AlarmManager.AlarmClockInfo(t, showPi), firePi(c, id));
        prefs(c).edit().putString("a" + id, a.toString()).apply();
    }

    static void cancel(Context c, int id) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        am.cancel(firePi(c, id));
        prefs(c).edit().remove("a" + id).apply();
    }

    static void rescheduleAll(Context c) {
        Map<String, ?> all = prefs(c).getAll();
        for (Object v : all.values()) {
            try {
                schedule(c, new JSONObject((String) v));
            } catch (Exception e) {
                // abaikan data rusak
            }
        }
    }
}
''')

tulis(os.path.join(JAVA, 'AlarmReceiver.java'), '''package __PKG__;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import org.json.JSONObject;

public class AlarmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        int id = intent.getIntExtra("id", -1);
        String s = AlarmScheduler.prefs(context).getString("a" + id, null);
        if (s == null) return;
        try {
            JSONObject a = new JSONObject(s);
            Intent svc = new Intent(context, AlarmService.class);
            svc.putExtra("id", id);
            svc.putExtra("h", a.optInt("h"));
            svc.putExtra("m", a.optInt("m"));
            svc.putExtra("label", a.optString("label", ""));
            svc.putExtra("uri", a.optString("uri", ""));
            if (Build.VERSION.SDK_INT >= 26) {
                context.startForegroundService(svc);
            } else {
                context.startService(svc);
            }
            if (a.optBoolean("repeat", false)) {
                AlarmScheduler.schedule(context, a);   // jadwalkan lagi untuk besok
            } else {
                AlarmScheduler.prefs(context).edit().remove("a" + id).apply();
            }
        } catch (Exception e) {
            // abaikan
        }
    }
}
''')

tulis(os.path.join(JAVA, 'BootReceiver.java'), '''package __PKG__;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        AlarmScheduler.rescheduleAll(context);
    }
}
''')

tulis(os.path.join(JAVA, 'AlarmService.java'), '''package __PKG__;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.content.res.AssetFileDescriptor;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.RingtoneManager;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.VibrationEffect;
import android.os.Vibrator;
import androidx.core.app.NotificationCompat;

public class AlarmService extends Service {
    static final String CHANNEL = "alarm_ring_v1";
    static final String ACT_STOP = "__PKG__.STOP";
    static volatile boolean ringing = false;
    static volatile String ringLabel = "";
    static volatile int ringH = 0;
    static volatile int ringM = 0;
    static volatile String sumberSuara = "";

    private MediaPlayer player;
    private Vibrator vibrator;
    private final Handler handler = new Handler(Looper.getMainLooper());

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACT_STOP.equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (intent == null) {
            stopSelf();
            return START_NOT_STICKY;
        }

        String label = intent.getStringExtra("label");
        if (label == null) label = "";
        int h = intent.getIntExtra("h", 0);
        int m = intent.getIntExtra("m", 0);
        String uri = intent.getStringExtra("uri");
        ringLabel = label;
        ringH = h;
        ringM = m;
        ringing = true;

        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(
                CHANNEL, "Alarm berbunyi", NotificationManager.IMPORTANCE_HIGH);
            ch.setSound(null, null);
            ch.enableVibration(false);
            ch.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            nm.createNotificationChannel(ch);
        }

        Intent open = new Intent(this, MainActivity.class);
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent openPi = PendingIntent.getActivity(this, 0, open,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Intent stop = new Intent(this, AlarmService.class);
        stop.setAction(ACT_STOP);
        PendingIntent stopPi = PendingIntent.getService(this, 1, stop,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        String waktu = (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
        Notification n = new NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("\\u23F0 " + (label.isEmpty() ? "Alarm" : label))
            .setContentText("Waktunya " + waktu)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setOngoing(true)
            .setFullScreenIntent(openPi, true)
            .setContentIntent(openPi)
            .addAction(0, "Matikan", stopPi)
            .build();

        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1001, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        } else {
            startForeground(1001, n);
        }

        mulaiSuara(uri);
        mulaiGetar();
        handler.removeCallbacksAndMessages(null);
        handler.postDelayed(this::stopSelf, 5 * 60 * 1000L);   // berhenti otomatis setelah 5 menit
        return START_NOT_STICKY;
    }

    private MediaPlayer buatPlayer() {
        MediaPlayer mp = new MediaPlayer();
        mp.setAudioAttributes(new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
            .build());
        mp.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
        return mp;
    }

    private void naikkanVolume() {
        try {
            AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
            int max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM);
            int cur = am.getStreamVolume(AudioManager.STREAM_ALARM);
            int min = Math.max(1, (int) Math.ceil(max * 0.6));
            if (cur < min) am.setStreamVolume(AudioManager.STREAM_ALARM, min, 0);
        } catch (Exception e) {
            // abaikan
        }
    }

    private boolean coba(Uri uri, String nama) {
        try {
            player = buatPlayer();
            player.setDataSource(this, uri);
            player.prepare();
            player.setLooping(true);
            player.start();
            sumberSuara = nama;
            return true;
        } catch (Exception e) {
            if (player != null) { try { player.release(); } catch (Exception x) { } }
            player = null;
            return false;
        }
    }

    private void mulaiSuara(String uri) {
        sumberSuara = "gagal";
        naikkanVolume();
        if (uri != null && !uri.isEmpty() && coba(Uri.parse(uri), "lagu pilihan")) return;

        // Cadangan 1: nada bip bawaan aplikasi
        try {
            player = buatPlayer();
            AssetFileDescriptor afd = getResources().openRawResourceFd(R.raw.alarm);
            player.setDataSource(afd.getFileDescriptor(), afd.getStartOffset(), afd.getLength());
            afd.close();
            player.prepare();
            player.setLooping(true);
            player.start();
            sumberSuara = "nada bawaan";
            return;
        } catch (Exception e) {
            if (player != null) { try { player.release(); } catch (Exception x) { } }
            player = null;
        }

        // Cadangan 2: nada alarm sistem
        coba(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM), "nada sistem");
    }

    private void mulaiGetar() {
        try {
            vibrator = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (vibrator == null) return;
            long[] pola = {0, 600, 400};
            if (Build.VERSION.SDK_INT >= 26) {
                vibrator.vibrate(VibrationEffect.createWaveform(pola, 0));
            } else {
                vibrator.vibrate(pola, 0);
            }
        } catch (Exception e) {
            // abaikan
        }
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (player != null) {
            try { player.stop(); } catch (Exception e) { }
            player.release();
            player = null;
        }
        if (vibrator != null) vibrator.cancel();
        ringing = false;
        super.onDestroy();
    }
}
''')

tulis(os.path.join(JAVA, 'AlarmPlugin.java'), '''package __PKG__;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import org.json.JSONObject;

@CapacitorPlugin(name = "AlarmNative")
public class AlarmPlugin extends Plugin {

    @PluginMethod
    public void pickSong(PluginCall call) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("audio/*");
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(call, i, "pickResult");
    }

    @ActivityCallback
    private void pickResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        if (result.getResultCode() != Activity.RESULT_OK
            || result.getData() == null || result.getData().getData() == null) {
            call.reject("dibatalkan");
            return;
        }
        Uri uri = result.getData().getData();
        try {
            getContext().getContentResolver().takePersistableUriPermission(
                uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (Exception e) {
            // sebagian penyedia berkas tidak mendukung izin permanen
        }
        JSObject r = new JSObject();
        r.put("uri", uri.toString());
        r.put("name", namaFile(uri));
        call.resolve(r);
    }

    private String namaFile(Uri uri) {
        String nama = "Lagu";
        try (Cursor c = getContext().getContentResolver()
                .query(uri, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (idx >= 0) nama = c.getString(idx);
            }
        } catch (Exception e) {
            // pakai nama bawaan
        }
        return nama;
    }

    @PluginMethod
    public void schedule(PluginCall call) {
        try {
            if (android.os.Build.VERSION.SDK_INT >= 31) {
                android.app.AlarmManager am = (android.app.AlarmManager)
                    getContext().getSystemService(Context.ALARM_SERVICE);
                if (!am.canScheduleExactAlarms()) {
                    Intent st = new Intent(android.provider.Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM);
                    st.setData(Uri.parse("package:" + getContext().getPackageName()));
                    st.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    getContext().startActivity(st);
                    call.reject("Izinkan izin Alarm dan pengingat untuk aplikasi ini, lalu tambahkan alarm lagi.");
                    return;
                }
            }
            JSONObject a = new JSONObject();
            a.put("id", call.getInt("id"));
            a.put("h", call.getInt("h"));
            a.put("m", call.getInt("m"));
            a.put("repeat", call.getBoolean("repeat", false));
            a.put("label", call.getString("label", ""));
            a.put("uri", call.getString("uri", ""));
            AlarmScheduler.schedule(getContext(), a);
            call.resolve();
        } catch (Exception e) {
            call.reject("Gagal menjadwalkan: " + e.getMessage());
        }
    }

    @PluginMethod
    public void cancel(PluginCall call) {
        Integer id = call.getInt("id");
        if (id != null) AlarmScheduler.cancel(getContext(), id);
        call.resolve();
    }

    @PluginMethod
    public void stop(PluginCall call) {
        Context c = getContext();
        c.stopService(new Intent(c, AlarmService.class));
        call.resolve();
    }

    @PluginMethod
    public void getRinging(PluginCall call) {
        JSObject r = new JSObject();
        r.put("ringing", AlarmService.ringing);
        r.put("label", AlarmService.ringLabel);
        r.put("h", AlarmService.ringH);
        r.put("m", AlarmService.ringM);
        r.put("sumber", AlarmService.sumberSuara);
        call.resolve(r);
    }

    @PluginMethod
    public void testRing(PluginCall call) {
        Context c = getContext();
        try {
            java.util.Calendar now = java.util.Calendar.getInstance();
            Intent svc = new Intent(c, AlarmService.class);
            svc.putExtra("id", 0);
            svc.putExtra("h", now.get(java.util.Calendar.HOUR_OF_DAY));
            svc.putExtra("m", now.get(java.util.Calendar.MINUTE));
            svc.putExtra("label", "Tes alarm");
            svc.putExtra("uri", call.getString("uri", ""));
            if (android.os.Build.VERSION.SDK_INT >= 26) {
                c.startForegroundService(svc);
            } else {
                c.startService(svc);
            }
            call.resolve();
        } catch (Exception e) {
            call.reject("Gagal memulai tes: " + e.getMessage());
        }
    }
}
''')

# ======================= WIDGET =======================

tulis(os.path.join(JAVA, 'ClockWidgetProvider.java'), '''package __PKG__;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;

public class ClockWidgetProvider extends AppWidgetProvider {
    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        Intent intent = new Intent(context, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pi = PendingIntent.getActivity(
            context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        for (int id : ids) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_clock);
            views.setOnClickPendingIntent(R.id.widget_root, pi);
            manager.updateAppWidget(id, views);
        }
    }
}
''')

tulis(os.path.join(MAIN, 'res', 'layout', 'widget_clock.xml'), '''<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:id="@+id/widget_root"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:orientation="vertical"
    android:gravity="center"
    android:paddingLeft="10dp"
    android:paddingRight="10dp"
    android:paddingTop="6dp"
    android:paddingBottom="6dp"
    android:background="@drawable/widget_bg">

    <TextClock
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:includeFontPadding="false"
        android:maxLines="1"
        android:format12Hour="hh:mm a"
        android:format24Hour="HH:mm"
        android:textColor="#FFFFFF"
        android:textSize="30sp"
        android:textStyle="bold" />

    <TextClock
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:includeFontPadding="false"
        android:maxLines="1"
        android:layout_marginTop="2dp"
        android:format12Hour="EEEE, d MMMM yyyy"
        android:format24Hour="EEEE, d MMMM yyyy"
        android:textColor="#CBD5E1"
        android:textSize="12sp" />
</LinearLayout>
''')

tulis(os.path.join(MAIN, 'res', 'drawable', 'widget_bg.xml'), '''<?xml version="1.0" encoding="utf-8"?>
<shape xmlns:android="http://schemas.android.com/apk/res/android" android:shape="rectangle">
    <solid android:color="#E60F172A" />
    <corners android:radius="20dp" />
    <stroke android:width="1dp" android:color="#33FFFFFF" />
</shape>
''')

tulis(os.path.join(MAIN, 'res', 'xml', 'clock_widget_info.xml'), '''<?xml version="1.0" encoding="utf-8"?>
<appwidget-provider xmlns:android="http://schemas.android.com/apk/res/android"
    android:minWidth="180dp"
    android:minHeight="110dp"
    android:updatePeriodMillis="0"
    android:initialLayout="@layout/widget_clock"
    android:resizeMode="horizontal|vertical"
    android:minResizeWidth="110dp"
    android:minResizeHeight="70dp"
    android:targetCellWidth="3"
    android:targetCellHeight="2"
    android:description="@string/widget_desc"
    android:previewLayout="@layout/widget_clock"
    android:widgetCategory="home_screen" />
''')

tulis(os.path.join(MAIN, 'res', 'values', 'widget_strings.xml'), '''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="widget_desc">Jam dan tanggal</string>
</resources>
''')

# ======================= NADA BAWAAN (cadangan bila lagu gagal diputar) =======================

raw = os.path.join(MAIN, 'res', 'raw')
os.makedirs(raw, exist_ok=True)
rate, detik = 22050, 20
with wave.open(os.path.join(raw, 'alarm.wav'), 'wb') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    frames = bytearray()
    for i in range(rate * detik):
        t = i / rate
        siklus = t % 2.0                 # 1 detik bip, 1 detik jeda
        pos = siklus % 0.25
        if siklus < 1.0 and pos < 0.15:
            env = min(1.0, pos / 0.01, (0.15 - pos) / 0.01)
            v = int(32767 * 0.6 * env * math.sin(2 * math.pi * 880 * t))
        else:
            v = 0
        frames += struct.pack('<h', v)
    w.writeframes(bytes(frames))

# ======================= MANIFEST =======================

mf = os.path.join(MAIN, 'AndroidManifest.xml')
with open(mf, encoding='utf-8') as f:
    s = f.read()

if 'ClockWidgetProvider' not in s:
    izin = '''<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
    <uses-permission android:name="android.permission.SCHEDULE_EXACT_ALARM" />
    <uses-permission android:name="android.permission.USE_EXACT_ALARM" />
    <uses-permission android:name="android.permission.USE_FULL_SCREEN_INTENT" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK" />
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
    <uses-permission android:name="android.permission.VIBRATE" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />
    '''
    komponen = '''
        <receiver
            android:name=".ClockWidgetProvider"
            android:exported="true"
            android:label="Jam Mercusuar">
            <intent-filter>
                <action android:name="android.appwidget.action.APPWIDGET_UPDATE" />
            </intent-filter>
            <meta-data
                android:name="android.appwidget.provider"
                android:resource="@xml/clock_widget_info" />
        </receiver>

        <receiver android:name=".AlarmReceiver" android:exported="false" />

        <receiver android:name=".BootReceiver" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>

        <service
            android:name=".AlarmService"
            android:exported="false"
            android:foregroundServiceType="mediaPlayback" />
    '''
    s = s.replace('<application', izin + '<application', 1)
    s = s.replace('</application>', komponen + '</application>', 1)
    with open(mf, 'w', encoding='utf-8') as f:
        f.write(s)

print('Patch Android selesai')
