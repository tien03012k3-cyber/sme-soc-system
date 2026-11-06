package com.sme.socalert;

import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.Build;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AppCompatActivity;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;

public class IncomingCallActivity extends AppCompatActivity {
    private MediaPlayer voicePlayer = null;
    private TextToSpeech tts = null;
    private boolean isTtsReady = false;
    private String serverUrl = "";
    private String alertDetails = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // BẬT SÁNG MÀN HÌNH VÀ BUNG RA ĐÈ LÊN MÀN HÌNH KHÓA (LOCK SCREEN)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
            KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
            if (km != null) km.requestDismissKeyguard(this, null);
        } else {
            getWindow().addFlags(
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED |
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON |
                    WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON |
                    WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
            );
        }

        setContentView(R.layout.activity_incoming_call);

        String title = getIntent().getStringExtra("title");
        alertDetails = getIntent().getStringExtra("details");
        if (alertDetails == null || alertDetails.isEmpty()) {
            alertDetails = "Cảnh báo an ninh mạng! Phát hiện sự cố khẩn cấp trên hệ thống!";
        }

        serverUrl = getIntent().getStringExtra("server_url");
        if (serverUrl == null || serverUrl.isEmpty()) {
            serverUrl = MainActivity.DEFAULT_SERVER_URL;
        }
        if (!serverUrl.endsWith("/")) serverUrl += "/";

        // Khởi tạo TextToSpeech dự phòng ngoại tuyến
        initTTS();

        TextView tvTitle = findViewById(R.id.tvCallTitle);
        TextView tvDetails = findViewById(R.id.tvCallDetails);
        TextView tvStatus = findViewById(R.id.tvCallStatus);
        View btnAnswer = findViewById(R.id.btnAnswerCall);
        View btnDecline = findViewById(R.id.btnDeclineCall);
        View layoutIncomingButtons = findViewById(R.id.layoutIncomingButtons);
        LinearLayout layoutSoar = findViewById(R.id.layoutSoar);
        Button btnShutdown = findViewById(R.id.btnSoarShutdown);
        Button btnLower = findViewById(R.id.btnSoarLower);
        Button btnOpenDashboard = findViewById(R.id.btnOpenDashboard);
        Button btnEndActiveCall = findViewById(R.id.btnEndActiveCall);

        if (title != null) tvTitle.setText(title);
        tvDetails.setText(alertDetails);

        btnAnswer.setOnClickListener(v -> {
            // 1. Tắt chuông điện thoại
            SOCService.stopRingtoneAndVibrate(this);

            // 2. Chuyển sang Loa ngoài (Loudspeaker) với âm lượng lớn
            routeAudioToSpeaker();

            // 3. Đổi trạng thái giao diện
            tvStatus.setText("🟢 CUỘC GỌI ĐANG KẾT NỐI • PHÁT QUA LOA NGOÀI");
            tvStatus.setTextColor(0xFF22C55E);
            if (layoutIncomingButtons != null) layoutIncomingButtons.setVisibility(View.GONE);
            if (layoutSoar != null) layoutSoar.setVisibility(View.VISIBLE);

            // 4. Phát âm thanh giọng nói AI (Ưu tiên MP3 từ Server, nếu lỗi tự động dùng TTS máy)
            playAIVoice(serverUrl + "api/voice_alert?t=" + System.currentTimeMillis());
        });

        btnDecline.setOnClickListener(v -> {
            stopVoice();
            SOCService.stopRingtoneAndVibrate(this);
            openDashboardActivity();
        });

        if (btnEndActiveCall != null) {
            btnEndActiveCall.setOnClickListener(v -> {
                stopVoice();
                SOCService.stopRingtoneAndVibrate(this);
                finish();
            });
        }

        btnOpenDashboard.setOnClickListener(v -> {
            stopVoice();
            SOCService.stopRingtoneAndVibrate(this);
            openDashboardActivity();
        });

        btnShutdown.setOnClickListener(v -> {
            sendSoarPost(serverUrl + "api/soar/shutdown", "{}");
            Toast.makeText(this, "🚨 ĐÃ PHÁT LỆNH TẮT MÁY WINDOWS!", Toast.LENGTH_LONG).show();
        });

        btnLower.setOnClickListener(v -> {
            sendSoarPost(serverUrl + "api/config", "{\"cpu_threshold\": 99.0, \"ram_threshold\": 99.0}");
            Toast.makeText(this, "⚡ ĐÃ HẠ TẢI HỆ THỐNG AN TOÀN!", Toast.LENGTH_LONG).show();
        });
    }

    private void initTTS() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS && tts != null) {
                int res = tts.setLanguage(new Locale("vi", "VN"));
                if (res != TextToSpeech.LANG_MISSING_DATA && res != TextToSpeech.LANG_NOT_SUPPORTED) {
                    isTtsReady = true;
                }
            }
        });
    }

    private void routeAudioToSpeaker() {
        try {
            AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            if (am != null) {
                am.setMode(AudioManager.MODE_NORMAL);
                am.setSpeakerphoneOn(true);
                int maxVol = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
                int targetVol = (int) (maxVol * 0.95);
                am.setStreamVolume(AudioManager.STREAM_MUSIC, targetVol, 0);
            }
        } catch (Exception ignored) {}
    }

    private void openDashboardActivity() {
        Intent mainIntent = new Intent(this, MainActivity.class);
        mainIntent.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        startActivity(mainIntent);
        finish();
    }

    private void playAIVoice(String audioUrl) {
        stopVoice();
        new Thread(() -> {
            boolean playSuccess = false;
            try {
                // 1. Tải file MP3 về bộ nhớ cache cục bộ
                File tempMp3 = new File(getCacheDir(), "latest_voice.mp3");
                URL url = new URL(audioUrl);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36");
                conn.setConnectTimeout(6000);
                conn.setReadTimeout(6000);

                if (conn.getResponseCode() == 200) {
                    InputStream in = conn.getInputStream();
                    FileOutputStream out = new FileOutputStream(tempMp3);
                    byte[] buffer = new byte[4096];
                    int len;
                    while ((len = in.read(buffer)) > 0) {
                        out.write(buffer, 0, len);
                    }
                    out.close();
                    in.close();

                    if (tempMp3.exists() && tempMp3.length() > 500) {
                        voicePlayer = new MediaPlayer();
                        voicePlayer.setAudioAttributes(new AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_MEDIA)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build());
                        voicePlayer.setDataSource(tempMp3.getAbsolutePath());
                        voicePlayer.prepare();
                        voicePlayer.start();
                        playSuccess = true;

                        voicePlayer.setOnCompletionListener(mp -> {
                            runOnUiThread(() -> {
                                TextView tvStatus = findViewById(R.id.tvCallStatus);
                                if (tvStatus != null) tvStatus.setText("✅ ĐÃ HOÀN THÀNH BẢN TIN CẢNH BÁO");
                            });
                        });
                    }
                }
                conn.disconnect();
            } catch (Exception e) {
                playSuccess = false;
            }

            // 2. Nếu không phát được MP3 qua mạng -> Dùng ngay Android Native TTS đọc to
            if (!playSuccess) {
                runOnUiThread(() -> {
                    speakViaFallbackTTS(alertDetails);
                });
            }
        }).start();
    }

    private void speakViaFallbackTTS(String text) {
        try {
            if (tts != null && isTtsReady) {
                tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "SOC_TTS_ALERT");
                TextView tvStatus = findViewById(R.id.tvCallStatus);
                if (tvStatus != null) tvStatus.setText("🟢 ĐANG ĐỌC GIỌNG NÓI AI (DỰ PHÒNG)");
            }
        } catch (Exception ignored) {}
    }

    private void stopVoice() {
        if (voicePlayer != null) {
            try {
                if (voicePlayer.isPlaying()) voicePlayer.stop();
                voicePlayer.release();
            } catch (Exception ignored) {}
            voicePlayer = null;
        }
        if (tts != null && tts.isSpeaking()) {
            try {
                tts.stop();
            } catch (Exception ignored) {}
        }
    }

    private void sendSoarPost(String endpointUrl, String jsonBody) {
        new Thread(() -> {
            try {
                URL url = new URL(endpointUrl);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setDoOutput(true);
                conn.setConnectTimeout(3000);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(jsonBody.getBytes());
                }
                conn.getResponseCode();
                conn.disconnect();
            } catch (Exception ignored) {}
        }).start();
    }

    @Override
    protected void onDestroy() {
        stopVoice();
        if (tts != null) {
            try {
                tts.shutdown();
            } catch (Exception ignored) {}
        }
        SOCService.stopRingtoneAndVibrate(this);
        super.onDestroy();
    }
}
