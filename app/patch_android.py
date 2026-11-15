"""Menambahkan widget jam, alarm native (lagu pilihan), suara bawaan, dan izin
ke proyek Android hasil `cap add android`."""
import json
import math
import os
import struct
import wave
from xml.sax.saxutils import escape

PKG = 'com.dikzz.realtimeclock'
MAIN = os.path.join('android', 'app', 'src', 'main')
JAVA = os.path.join(MAIN, 'java', *PKG.split('.'))


# Nama aplikasi diambil dari capacitor.config.json (appName)
try:
    with open('capacitor.config.json', encoding='utf-8') as f:
        NAMA = json.load(f).get('appName', 'Jam')
except Exception:
    NAMA = 'Jam'


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

    // mask: 0 = sekali; bit i = hari ke-i (0 = Minggu ... 6 = Sabtu)
    static long nextTime(int h, int m, int mask) {
        long now = System.currentTimeMillis();
        for (int i = 0; i < 8; i++) {
            Calendar c = Calendar.getInstance();
            c.add(Calendar.DAY_OF_YEAR, i);
            c.set(Calendar.HOUR_OF_DAY, h);
            c.set(Calendar.MINUTE, m);
            c.set(Calendar.SECOND, 0);
            c.set(Calendar.MILLISECOND, 0);
            int dow = c.get(Calendar.DAY_OF_WEEK) - 1;
            boolean cocok = mask == 0 || (mask & (1 << dow)) != 0;
            if (cocok && c.getTimeInMillis() > now) return c.getTimeInMillis();
        }
        return now + 86400000L;
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
        long t = nextTime(a.getInt("h"), a.getInt("m"), a.optInt("days", 0));
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
    static void mulai(Context context, Intent svc) {
        if (Build.VERSION.SDK_INT >= 26) {
            context.startForegroundService(svc);
        } else {
            context.startService(svc);
        }
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        try {
            Intent svc = new Intent(context, AlarmService.class);
            if ("__PKG__.SNOOZE".equals(intent.getAction())) {
                // Alarm tunda: semua data sudah ada di intent
                if (intent.getExtras() != null) svc.putExtras(intent.getExtras());
                mulai(context, svc);
                return;
            }
            int id = intent.getIntExtra("id", -1);
            String s = AlarmScheduler.prefs(context).getString("a" + id, null);
            if (s == null) return;
            JSONObject a = new JSONObject(s);
            svc.putExtra("id", id);
            svc.putExtra("h", a.optInt("h"));
            svc.putExtra("m", a.optInt("m"));
            svc.putExtra("label", a.optString("label", ""));
            svc.putExtra("uri", a.optString("uri", ""));
            svc.putExtra("vib", a.optBoolean("vib", true));
            svc.putExtra("snMin", a.optInt("snMin", 0));
            svc.putExtra("snLeft", a.optInt("snCount", 0));
            mulai(context, svc);
            if (a.optInt("days", 0) != 0) {
                AlarmScheduler.schedule(context, a);   // jadwalkan lagi untuk hari berikutnya
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
        WidgetUpdater.refreshAll(context);
    }
}
''')

tulis(os.path.join(JAVA, 'AlarmService.java'), '''package __PKG__;

import android.app.AlarmManager;
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
    static final String ACT_SNOOZE = "__PKG__.SNOOZE_NOW";
    static volatile int curId = 0;
    static volatile String curLabel = "";
    static volatile String curUri = "";
    static volatile boolean curVib = true;
    static volatile int curSnMin = 0;
    static volatile int curSnLeft = 0;
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
        if (intent != null && ACT_SNOOZE.equals(intent.getAction())) {
            tunda();
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
        curId = intent.getIntExtra("id", 0);
        curLabel = label;
        curUri = uri == null ? "" : uri;
        curVib = intent.getBooleanExtra("vib", true);
        curSnMin = intent.getIntExtra("snMin", 0);
        curSnLeft = intent.getIntExtra("snLeft", 0);
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
        NotificationCompat.Builder nb = new NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("\\u23F0 " + (label.isEmpty() ? "Alarm" : label))
            .setContentText("Waktunya " + waktu)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setOngoing(true)
            .setFullScreenIntent(openPi, true)
            .setContentIntent(openPi)
            .addAction(0, "Matikan", stopPi);
        if (curSnMin > 0 && curSnLeft > 0) {
            Intent sn = new Intent(this, AlarmService.class);
            sn.setAction(ACT_SNOOZE);
            PendingIntent snPi = PendingIntent.getService(this, 2, sn,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            nb.addAction(0, "Tunda " + curSnMin + " mnt", snPi);
        }
        Notification n = nb.build();

        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1001, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        } else {
            startForeground(1001, n);
        }

        mulaiSuara(uri);
        if (curVib) mulaiGetar();
        handler.removeCallbacksAndMessages(null);
        handler.postDelayed(this::stopSelf, 5 * 60 * 1000L);   // berhenti otomatis setelah 5 menit
        return START_NOT_STICKY;
    }

    private void tunda() {
        try {
            Intent i = new Intent(this, AlarmReceiver.class);
            i.setAction("__PKG__.SNOOZE");
            i.putExtra("id", curId);
            i.putExtra("h", ringH);
            i.putExtra("m", ringM);
            i.putExtra("label", curLabel);
            i.putExtra("uri", curUri);
            i.putExtra("vib", curVib);
            i.putExtra("snMin", curSnMin);
            i.putExtra("snLeft", Math.max(0, curSnLeft - 1));
            PendingIntent pi = PendingIntent.getBroadcast(this, curId + 500000, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            long t = System.currentTimeMillis() + curSnMin * 60000L;
            AlarmManager am = (AlarmManager) getSystemService(ALARM_SERVICE);
            am.setAlarmClock(new AlarmManager.AlarmClockInfo(t, pi), pi);
        } catch (Exception e) {
            // abaikan
        }
        stopSelf();
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
            a.put("days", call.getInt("days", 0));
            a.put("vib", call.getBoolean("vib", true));
            a.put("snMin", call.getInt("snMin", 0));
            a.put("snCount", call.getInt("snCount", 0));
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
        r.put("canSnooze", AlarmService.curSnMin > 0 && AlarmService.curSnLeft > 0);
        call.resolve(r);
    }

    @PluginMethod
    public void snooze(PluginCall call) {
        Context c = getContext();
        Intent i = new Intent(c, AlarmService.class);
        i.setAction(AlarmService.ACT_SNOOZE);
        try { c.startService(i); } catch (Exception e) { }
        call.resolve();
    }

    @PluginMethod
    public void setBirthday(PluginCall call) {
        android.content.SharedPreferences.Editor e =
            getContext().getSharedPreferences("jam_widget", 0).edit();
        e.putBoolean("on", call.getBoolean("on", false));
        e.putInt("d", call.getInt("d", 1));
        e.putInt("m", call.getInt("m", 0));
        e.putInt("y", call.getInt("y", 0));
        e.putString("nama", call.getString("nama", ""));
        e.apply();
        WidgetUpdater.refreshAll(getContext());
        call.resolve();
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

import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.Context;

public class ClockWidgetProvider extends AppWidgetProvider {
    protected int layoutId() {
        return R.layout.widget_clock;
    }

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        WidgetUpdater.update(context, manager, ids, layoutId());
        WidgetUpdater.schedule(context);
    }

    @Override
    public void onEnabled(Context context) {
        WidgetUpdater.schedule(context);
    }
}
''')

tulis(os.path.join(JAVA, 'WidgetUpdater.java'), '''package __PKG__;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.view.View;
import android.widget.RemoteViews;
import java.util.Calendar;

public class WidgetUpdater {
    static String salam(int h) {
        if (h >= 4 && h < 11) return "\\u2600\\uFE0F Selamat Pagi";
        if (h >= 11 && h < 15) return "\\uD83C\\uDF24\\uFE0F Selamat Siang";
        if (h >= 15 && h < 18) return "\\uD83C\\uDF07 Selamat Sore";
        return "\\uD83C\\uDF19 Selamat Malam";
    }

    static Calendar tgl(int y, int m, int d) {
        Calendar c = Calendar.getInstance();
        c.clear();
        c.set(y, m, d);
        return c;
    }

    static Calendar targetUltah(int y, int m, int d) {
        boolean kabisat = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
        if (m == 1 && d == 29 && !kabisat) d = 28;
        return tgl(y, m, d);
    }

    static String ultah(Context c) {
        SharedPreferences p = c.getSharedPreferences("jam_widget", 0);
        if (!p.getBoolean("on", false)) return "";
        int d = p.getInt("d", 1), m = p.getInt("m", 0), y = p.getInt("y", 0);
        String nama = p.getString("nama", "");
        Calendar now = Calendar.getInstance();
        int th = now.get(Calendar.YEAR);
        Calendar hariIni = tgl(th, now.get(Calendar.MONTH), now.get(Calendar.DAY_OF_MONTH));
        Calendar t = targetUltah(th, m, d);
        if (t.before(hariIni)) t = targetUltah(th + 1, m, d);
        long hari = Math.round((t.getTimeInMillis() - hariIni.getTimeInMillis()) / 86400000.0);
        if (hari == 0) {
            int umur = y > 0 ? th - y : 0;
            return "\\uD83C\\uDF89 Selamat ulang tahun" + (umur > 0 ? " ke-" + umur : "")
                + (nama.isEmpty() ? "" : ", " + nama) + "!";
        }
        return "\\uD83C\\uDF82 " + hari + " hari lagi menuju hari ulang tahun"
            + (nama.isEmpty() ? "" : " " + nama);
    }

    static void update(Context c, AppWidgetManager mgr, int[] ids, int layout) {
        Intent i = new Intent(c, MainActivity.class);
        i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pi = PendingIntent.getActivity(c, 0, i,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String s = salam(Calendar.getInstance().get(Calendar.HOUR_OF_DAY));
        String u = ultah(c);
        for (int id : ids) {
            RemoteViews v = new RemoteViews(c.getPackageName(), layout);
            v.setOnClickPendingIntent(R.id.widget_root, pi);
            v.setTextViewText(R.id.widget_greeting, s);
            v.setTextViewText(R.id.widget_birthday, u);
            v.setViewVisibility(R.id.widget_birthday, u.isEmpty() ? View.GONE : View.VISIBLE);
            mgr.updateAppWidget(id, v);
        }
    }

    static void refreshAll(Context c) {
        AppWidgetManager m = AppWidgetManager.getInstance(c);
        int[] a = m.getAppWidgetIds(new ComponentName(c, ClockWidgetProvider.class));
        if (a.length > 0) update(c, m, a, R.layout.widget_clock);
        int[] b = m.getAppWidgetIds(new ComponentName(c, ClockWidgetSecondsProvider.class));
        if (b.length > 0) update(c, m, b, R.layout.widget_clock_seconds);
        schedule(c);
    }

    // Segarkan lagi pada awal jam berikutnya (ganti sapaan dan hitung mundur)
    static void schedule(Context c) {
        Calendar n = Calendar.getInstance();
        n.add(Calendar.HOUR_OF_DAY, 1);
        n.set(Calendar.MINUTE, 0);
        n.set(Calendar.SECOND, 5);
        n.set(Calendar.MILLISECOND, 0);
        PendingIntent pi = PendingIntent.getBroadcast(c, 7001,
            new Intent(c, WidgetRefreshReceiver.class),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, n.getTimeInMillis(), pi);
    }
}
''')

tulis(os.path.join(JAVA, 'WidgetRefreshReceiver.java'), '''package __PKG__;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class WidgetRefreshReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        WidgetUpdater.refreshAll(context);
    }
}
''')

tulis(os.path.join(JAVA, 'ClockWidgetSecondsProvider.java'), '''package __PKG__;

public class ClockWidgetSecondsProvider extends ClockWidgetProvider {
    @Override
    protected int layoutId() {
        return R.layout.widget_clock_seconds;
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

    <TextView
        android:id="@+id/widget_greeting"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:includeFontPadding="false"
        android:maxLines="1"
        android:text="Selamat datang"
        android:textColor="#FDE68A"
        android:textSize="12sp"
        android:textStyle="bold" />

    <TextClock
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:includeFontPadding="false"
        android:maxLines="1"
        android:format12Hour="hh:mm a"
        android:format24Hour="hh:mm a"
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
    <TextView
        android:id="@+id/widget_birthday"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:layout_marginTop="2dp"
        android:ellipsize="end"
        android:includeFontPadding="false"
        android:maxLines="1"
        android:textColor="#FBCFE8"
        android:textSize="11sp"
        android:visibility="gone" />
</LinearLayout>
''')

tulis(os.path.join(MAIN, 'res', 'layout', 'widget_clock_seconds.xml'), '''<?xml version="1.0" encoding="utf-8"?>
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

    <TextView
        android:id="@+id/widget_greeting"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:includeFontPadding="false"
        android:maxLines="1"
        android:text="Selamat datang"
        android:textColor="#FDE68A"
        android:textSize="12sp"
        android:textStyle="bold" />

    <TextClock
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:includeFontPadding="false"
        android:maxLines="1"
        android:format12Hour="hh:mm:ss a"
        android:format24Hour="hh:mm:ss a"
        android:textColor="#FFFFFF"
        android:textSize="26sp"
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
    <TextView
        android:id="@+id/widget_birthday"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:layout_marginTop="2dp"
        android:ellipsize="end"
        android:includeFontPadding="false"
        android:maxLines="1"
        android:textColor="#FBCFE8"
        android:textSize="11sp"
        android:visibility="gone" />
</LinearLayout>
''')

tulis(os.path.join(MAIN, 'res', 'xml', 'clock_widget_seconds_info.xml'), '''<?xml version="1.0" encoding="utf-8"?>
<appwidget-provider xmlns:android="http://schemas.android.com/apk/res/android"
    android:minWidth="250dp"
    android:minHeight="110dp"
    android:updatePeriodMillis="0"
    android:initialLayout="@layout/widget_clock_seconds"
    android:resizeMode="horizontal|vertical"
    android:minResizeWidth="180dp"
    android:minResizeHeight="70dp"
    android:targetCellWidth="4"
    android:targetCellHeight="2"
    android:description="@string/widget_desc_seconds"
    android:previewLayout="@layout/widget_clock_seconds"
    android:widgetCategory="home_screen" />
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
    <string name="widget_desc">Jam (AM/PM) dan tanggal</string>
    <string name="widget_desc_seconds">Jam dengan detik (AM/PM) dan tanggal</string>
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


# ======================= IKON APLIKASI (opsional: app/icon.png) =======================

if os.path.exists('icon.png'):
    from PIL import Image, ImageDraw

    src = Image.open('icon.png').convert('RGBA')
    w, h = src.size
    m = min(w, h)
    kiri, atas = (w - m) // 2, (h - m) // 2
    src = src.crop((kiri, atas, kiri + m, atas + m))   # dipotong jadi persegi di tengah

    res = os.path.join(MAIN, 'res')
    for nama, ukuran in {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}.items():
        folder = os.path.join(res, 'mipmap-' + nama)
        os.makedirs(folder, exist_ok=True)

        persegi = src.resize((ukuran, ukuran), Image.LANCZOS)
        persegi.save(os.path.join(folder, 'ic_launcher.png'))

        topeng = Image.new('L', (ukuran, ukuran), 0)
        ImageDraw.Draw(topeng).ellipse((0, 0, ukuran - 1, ukuran - 1), fill=255)
        bulat = persegi.copy()
        bulat.putalpha(topeng)
        bulat.save(os.path.join(folder, 'ic_launcher_round.png'))

        # Lapisan depan ikon adaptif (kanvas 108dp, gambar di area aman)
        kanvas_ukuran = int(ukuran * 108 / 48)
        kanvas = Image.new('RGBA', (kanvas_ukuran, kanvas_ukuran), (0, 0, 0, 0))
        dalam = int(kanvas_ukuran * 0.64)
        gambar = src.resize((dalam, dalam), Image.LANCZOS)
        pos = (kanvas_ukuran - dalam) // 2
        kanvas.paste(gambar, (pos, pos), gambar)
        kanvas.save(os.path.join(folder, 'ic_launcher_foreground.png'))

    # Latar ikon adaptif memakai warna di sudut kiri atas gambar
    px = src.getpixel((2, 2))
    warna = '#%02X%02X%02X' % (px[0], px[1], px[2])
    tulis(os.path.join(res, 'values', 'jam_icon_colors.xml'), f'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="jam_icon_bg">{warna}</color>
</resources>
''')
    adaptif = '''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/jam_icon_bg" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
'''
    tulis(os.path.join(res, 'mipmap-anydpi-v26', 'ic_launcher.xml'), adaptif)
    tulis(os.path.join(res, 'mipmap-anydpi-v26', 'ic_launcher_round.xml'), adaptif)
    print('Ikon aplikasi dipasang dari icon.png')

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
            android:label="Jam Ringkas">
            <intent-filter>
                <action android:name="android.appwidget.action.APPWIDGET_UPDATE" />
            </intent-filter>
            <meta-data
                android:name="android.appwidget.provider"
                android:resource="@xml/clock_widget_info" />
        </receiver>

        <receiver
            android:name=".ClockWidgetSecondsProvider"
            android:exported="true"
            android:label="Jam + Detik">
            <intent-filter>
                <action android:name="android.appwidget.action.APPWIDGET_UPDATE" />
            </intent-filter>
            <meta-data
                android:name="android.appwidget.provider"
                android:resource="@xml/clock_widget_seconds_info" />
        </receiver>

        <receiver android:name=".AlarmReceiver" android:exported="false" />

        <receiver android:name=".WidgetRefreshReceiver" android:exported="false" />

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
    s = s.replace('</application>', komponen.replace('__NAMA__', escape(NAMA)) + '</application>', 1)
    with open(mf, 'w', encoding='utf-8') as f:
        f.write(s)

# ======================= VERSI APLIKASI (dari package.json) =======================

import re

try:
    with open('package.json', encoding='utf-8') as f:
        versi = str(json.load(f).get('version', '1.0.0'))
except Exception:
    versi = '1.0.0'

angka = [int(x) for x in re.findall(r'\d+', versi)[:3]] + [0, 0, 0]
kode = angka[0] * 10000 + angka[1] * 100 + angka[2]    # 1.2.3 -> 10203
kode = max(kode, 1)

gradle = os.path.join('android', 'app', 'build.gradle')
if os.path.exists(gradle):
    with open(gradle, encoding='utf-8') as f:
        g = f.read()
    g = re.sub(r'versionCode\s+\d+', 'versionCode %d' % kode, g, count=1)
    g = re.sub(r'versionName\s+"[^"]*"', 'versionName "%s"' % versi, g, count=1)
    with open(gradle, 'w', encoding='utf-8') as f:
        f.write(g)
    print('Versi aplikasi: %s (kode %d)' % (versi, kode))

print('Patch Android selesai')
