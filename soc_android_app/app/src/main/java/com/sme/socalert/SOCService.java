package com.sme.socalert;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.IBinder;
import android.os.VibrationEffect;
import android.os.Vibrator;
import androidx.core.app.NotificationCompat;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

public class SOCService extends Service {
    public static final String CHANNEL_ID = "soc_emergency_channel";
    public static final String NOTIF_CHANNEL_ID = "soc_status_channel";
    private static MediaPlayer ringtonePlayer = null;
    private static Vibrator vibratorInstance = null;

    private boolean isRunning = false;
    private int lastHandledAlertId = 0;
    private SharedPreferences prefs;

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences("soc_prefs", MODE_PRIVATE);
        sanitizeSavedUrl();
        createNotificationChannels();
        startForeground(1001, createStatusNotification("Đang giám sát sự cố an ninh & tổng đài AI 24/7"));
        startMonitoringLoop();
    }

    private void sanitizeSavedUrl() {
        String saved = prefs.getString("server_url", MainActivity.DEFAULT_SERVER_URL);
        if (saved == null || saved.isEmpty()
                || saved.contains("trycloudflare.com")
                || saved.contains("proceeds-develops")
                || saved.contains("albuquerque")
                || saved.contains("crystal")
                || saved.contains("sticker-lincoln")) {
            prefs.edit().putString("server_url", MainActivity.DEFAULT_SERVER_URL).apply();
        }
    }

    private void createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm == null) return;

            // 1. Channel trạng thái ngầm thường
            NotificationChannel statusCh = new NotificationChannel(
                    NOTIF_CHANNEL_ID,
                    "SOC Trực ban Trạng thái",
                    NotificationManager.IMPORTANCE_LOW
            );
            statusCh.setDescription("Thông báo hiển thị ứng dụng đang bảo vệ ngầm");
            nm.createNotificationChannel(statusCh);

            // 2. Channel cuộc gọi khẩn cấp (Ưu tiên tối đa, bật màn hình)
            NotificationChannel callCh = new NotificationChannel(
                    CHANNEL_ID,
                    "SOC Cuộc gọi Khẩn cấp",
                    NotificationManager.IMPORTANCE_HIGH
            );
            callCh.setDescription("Bật sáng màn hình và đổ chuông cuộc gọi khẩn cấp");
            callCh.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            callCh.setBypassDnd(true);

            Uri ringUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
            AudioAttributes audioAttributes = new AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .build();
            callCh.setSound(ringUri, audioAttributes);
            callCh.enableVibration(true);
            callCh.setVibrationPattern(new long[]{0, 500, 200, 500, 200, 800});
            nm.createNotificationChannel(callCh);
        }
    }

    private Notification createStatusNotification(String statusText) {
        Intent openApp = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, openApp,
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0
        );

        return new NotificationCompat.Builder(this, NOTIF_CHANNEL_ID)
                .setContentTitle("🛡️ SOC Alert - Đang trực ban")
                .setContentText(statusText)
                .setSmallIcon(R.drawable.ic_shield)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }

    private void startMonitoringLoop() {
        if (isRunning) return;
        isRunning = true;

        new Thread(() -> {
            while (isRunning) {
                try {
                    String serverUrl = prefs.getString("server_url", MainActivity.DEFAULT_SERVER_URL);
                    if (!serverUrl.endsWith("/")) serverUrl += "/";

                    URL url = new URL(serverUrl + "api/voice_status");
                    HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                    conn.setRequestMethod("GET");
                    conn.setConnectTimeout(4000);
                    conn.setReadTimeout(4000);

                    if (conn.getResponseCode() == 200) {
                        BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                        StringBuilder sb = new StringBuilder();
                        String line;
                        while ((line = reader.readLine()) != null) sb.append(line);
                        reader.close();

                        JSONObject json = new JSONObject(sb.toString());
                        int alertId = json.optInt("alert_id", 0);
                        String title = json.optString("title", "Cảnh báo khẩn cấp");
                        String text = json.optString("text", "Phát hiện sự cố an ninh mạng!");
                        long alertTimestamp = (long) json.optDouble("timestamp", 0);
                        long nowSec = System.currentTimeMillis() / 1000;

                        boolean isCpuRam = title.toLowerCase().contains("cpu")
                                || title.toLowerCase().contains("ram")
                                || text.toLowerCase().contains("cpu")
                                || text.toLowerCase().contains("ram")
                                || title.toLowerCase().contains("quá tải");

                        if (lastHandledAlertId == 0) {
                            lastHandledAlertId = alertId;
                            // Nếu sự cố vừa mới phát sinh trong vòng 12 giây trước khi mở app, vẫn gọi chuông ngay (trừ khi là quá tải CPU/RAM)!
                            if (alertId > 0 && Math.abs(nowSec - alertTimestamp) <= 12 && !isCpuRam) {
                                triggerEmergencyCall(title, text, serverUrl);
                            }
                        } else if (alertId > lastHandledAlertId) {
                            lastHandledAlertId = alertId;
                            if (!isCpuRam) {
                                triggerEmergencyCall(title, text, serverUrl);
                            }
                        }
                    }
                    conn.disconnect();
                } catch (Exception ignored) {
                    // Ignore network glitches, retry in loop
                }

                try {
                    Thread.sleep(2000);
                } catch (InterruptedException ignored) {}
            }
        }).start();
    }

    public void triggerEmergencyCall(String title, String details, String serverUrl) {
        // 1. Bật chuông điện thoại reo liên tục
        startRingtoneAndVibrate(this);

        // 2. Tạo Intent mở IncomingCallActivity toàn màn hình
        Intent callIntent = new Intent(this, IncomingCallActivity.class);
        callIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        callIntent.putExtra("title", title);
        callIntent.putExtra("details", details);
        callIntent.putExtra("server_url", serverUrl);

        PendingIntent fullScreenPendingIntent = PendingIntent.getActivity(
                this, 1002, callIntent,
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? (PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE) : PendingIntent.FLAG_UPDATE_CURRENT
        );

        // 3. Bắn Full-Screen Notification (Đánh thức màn hình khóa sáng đèn)
        NotificationCompat.Builder notifBuilder = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_shield)
                .setContentTitle(title)
                .setContentText(details)
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setAutoCancel(false)
                .setOngoing(true)
                .setFullScreenIntent(fullScreenPendingIntent, true)
                .setContentIntent(fullScreenPendingIntent);

        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) {
            nm.notify(2002, notifBuilder.build());
        }

        // 4. Mở thẳng Activity nếu có quyền
        try {
            startActivity(callIntent);
        } catch (Exception ignored) {}
    }

    public static synchronized void startRingtoneAndVibrate(Context context) {
        stopRingtoneAndVibrate(context);
        try {
            Uri alert = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
            if (alert == null) {
                alert = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
            }
            ringtonePlayer = new MediaPlayer();
            ringtonePlayer.setDataSource(context, alert);
            ringtonePlayer.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build());
            ringtonePlayer.setLooping(true);
            ringtonePlayer.prepare();
            ringtonePlayer.start();
        } catch (Exception ignored) {}

        try {
            vibratorInstance = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
            if (vibratorInstance != null) {
                long[] pattern = {0, 600, 300, 600, 300, 1000};
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    vibratorInstance.vibrate(VibrationEffect.createWaveform(pattern, 0));
                } else {
                    vibratorInstance.vibrate(pattern, 0);
                }
            }
        } catch (Exception ignored) {}
    }

    public static synchronized void stopRingtoneAndVibrate(Context context) {
        if (ringtonePlayer != null) {
            try {
                if (ringtonePlayer.isPlaying()) ringtonePlayer.stop();
                ringtonePlayer.release();
            } catch (Exception ignored) {}
            ringtonePlayer = null;
        }
        if (vibratorInstance != null) {
            try {
                vibratorInstance.cancel();
            } catch (Exception ignored) {}
            vibratorInstance = null;
        }
        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) {
            nm.cancel(2002);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && intent.getBooleanExtra("test_call", false)) {
            String serverUrl = prefs.getString("server_url", MainActivity.DEFAULT_SERVER_URL);
            triggerEmergencyCall(
                    "Thử nghiệm cuộc gọi báo động",
                    "Cảnh báo thử nghiệm! Kết nối tổng đài giọng nói AI và ứng dụng di động SOC thành công!",
                    serverUrl
            );
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        isRunning = false;
        stopRingtoneAndVibrate(this);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
