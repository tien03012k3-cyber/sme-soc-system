package com.sme.socalert;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import com.google.android.material.textfield.TextInputEditText;

import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends AppCompatActivity {
    public static final String DEFAULT_SERVER_URL = "http://70.153.83.137";

    private SharedPreferences prefs;
    private WebView webView;
    private ProgressBar progressBar;
    private SwipeRefreshLayout swipeRefresh;
    private TextView tvStatusBadge;
    private LinearLayout layoutError;
    private TextView tvErrorDetails;
    private String currentServerUrl;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences("soc_prefs", MODE_PRIVATE);

        // Tự động dọn dẹp các đường link Cloudflare cũ đã hết hạn từ các phiên trước
        sanitizeSavedUrl();

        currentServerUrl = prefs.getString("server_url", DEFAULT_SERVER_URL);

        // Bind Views
        webView = findViewById(R.id.webViewDashboard);
        progressBar = findViewById(R.id.progressBar);
        swipeRefresh = findViewById(R.id.swipeRefreshLayout);
        tvStatusBadge = findViewById(R.id.tvStatusBadge);
        layoutError = findViewById(R.id.layoutError);
        tvErrorDetails = findViewById(R.id.tvErrorDetails);

        Button btnQuickTest = findViewById(R.id.btnQuickTest);
        ImageButton btnSettings = findViewById(R.id.btnSettings);
        Button btnRetry = findViewById(R.id.btnRetry);
        Button btnChangeUrl = findViewById(R.id.btnChangeUrl);

        if (swipeRefresh != null) {
            swipeRefresh.setColorSchemeColors(0xFF0284C7, 0xFF38BDF8, 0xFF10B981);
            swipeRefresh.setOnRefreshListener(() -> {
                webView.reload();
            });
            // Chỉ cho phép kéo refresh khi đang ở đỉnh trang web
            webView.getViewTreeObserver().addOnScrollChangedListener(() -> {
                if (webView.getScrollY() == 0) {
                    swipeRefresh.setEnabled(true);
                } else {
                    swipeRefresh.setEnabled(false);
                }
            });
        }

        // Setup WebView với đầy đủ JavaScript và chế độ hiển thị Dashboard
        setupWebView();

        btnQuickTest.setOnClickListener(v -> triggerTestCall());

        btnSettings.setOnClickListener(v -> showSettingsDialog());

        btnRetry.setOnClickListener(v -> {
            layoutError.setVisibility(View.GONE);
            webView.setVisibility(View.VISIBLE);
            loadDashboard();
        });

        btnChangeUrl.setOnClickListener(v -> showSettingsDialog());

        // Permissions & Background Service
        requestPermissions();
        startSOCService();

        // Load Initial Dashboard
        loadDashboard();
    }

    private void sanitizeSavedUrl() {
        String saved = prefs.getString("server_url", DEFAULT_SERVER_URL);
        if (saved == null || saved.isEmpty()
                || saved.contains("trycloudflare.com")
                || saved.contains("proceeds-develops")
                || saved.contains("albuquerque")
                || saved.contains("crystal")
                || saved.contains("sticker-lincoln")) {
            prefs.edit().putString("server_url", DEFAULT_SERVER_URL).apply();
        }
    }

    private void setupWebView() {
        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setLoadWithOverviewMode(true);
        ws.setUseWideViewPort(true);
        ws.setSupportZoom(true);
        ws.setBuiltInZoomControls(true);
        ws.setDisplayZoomControls(false);
        ws.setCacheMode(WebSettings.LOAD_DEFAULT);
        ws.setMediaPlaybackRequiresUserGesture(false);

        webView.setVerticalScrollBarEnabled(true);
        webView.setHorizontalScrollBarEnabled(true);

        CookieManager.getInstance().setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
            CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);
        }

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                if (newProgress < 100) {
                    progressBar.setVisibility(View.VISIBLE);
                    progressBar.setProgress(newProgress);
                } else {
                    progressBar.setVisibility(View.GONE);
                }
            }

            @Override
            public boolean onConsoleMessage(ConsoleMessage cm) {
                Log.d("SOC_WEBVIEW", cm.message() + " -- From line " + cm.lineNumber() + " of " + cm.sourceId());
                return true;
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                progressBar.setVisibility(View.VISIBLE);
                layoutError.setVisibility(View.GONE);
                webView.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progressBar.setVisibility(View.GONE);
                if (swipeRefresh != null) swipeRefresh.setRefreshing(false);
                tvStatusBadge.setText("🟢 TRỰC TUYẾN");
                tvStatusBadge.setBackgroundColor(0xFF16A34A);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP && request.isForMainFrame()) {
                    showErrorState("Lỗi kết nối máy chủ SOC: " + (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? error.getDescription() : "Mạng không khả dụng"));
                }
            }
        });
    }

    private void loadDashboard() {
        sanitizeSavedUrl();
        currentServerUrl = prefs.getString("server_url", DEFAULT_SERVER_URL).trim();
        if (!currentServerUrl.startsWith("http://") && !currentServerUrl.startsWith("https://")) {
            currentServerUrl = "https://" + currentServerUrl;
        }
        if (!currentServerUrl.endsWith("/")) currentServerUrl += "/";

        progressBar.setVisibility(View.VISIBLE);
        layoutError.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        webView.loadUrl(currentServerUrl);
    }

    private void showErrorState(String details) {
        progressBar.setVisibility(View.GONE);
        if (swipeRefresh != null) swipeRefresh.setRefreshing(false);
        webView.setVisibility(View.GONE);
        layoutError.setVisibility(View.VISIBLE);
        tvErrorDetails.setText(details + "\nĐịa chỉ hiện tại: " + currentServerUrl);
        tvStatusBadge.setText("🔴 MẤT KẾT NỐI");
        tvStatusBadge.setBackgroundColor(0xFFEF4444);
    }

    private void showSettingsDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        View dialogView = LayoutInflater.from(this).inflate(R.layout.dialog_settings, null);
        builder.setView(dialogView);

        AlertDialog dialog = builder.create();
        if (dialog.getWindow() != null) {
            dialog.getWindow().setBackgroundDrawableResource(android.R.color.transparent);
        }

        TextInputEditText etUrl = dialogView.findViewById(R.id.etDialogServerUrl);
        Button btnSave = dialogView.findViewById(R.id.btnDialogSave);
        Button btnTest = dialogView.findViewById(R.id.btnDialogTestCall);
        Button btnBattery = dialogView.findViewById(R.id.btnDialogBattery);
        Button btnClose = dialogView.findViewById(R.id.btnDialogClose);

        String savedUrl = prefs.getString("server_url", DEFAULT_SERVER_URL);
        etUrl.setText(savedUrl);

        btnSave.setOnClickListener(v -> {
            String newUrl = etUrl.getText() != null ? etUrl.getText().toString().trim() : "";
            if (!newUrl.isEmpty()) {
                if (!newUrl.startsWith("http://") && !newUrl.startsWith("https://")) {
                    newUrl = "https://" + newUrl;
                }
                prefs.edit().putString("server_url", newUrl).apply();
                currentServerUrl = newUrl;
                Toast.makeText(this, "✅ Đã lưu cấu hình máy chủ SOC!", Toast.LENGTH_SHORT).show();

                // Khởi động lại service ngầm với link mới
                startSOCService();
                loadDashboard();
                dialog.dismiss();
            } else {
                Toast.makeText(this, "⚠️ Vui lòng nhập địa chỉ máy chủ hợp lệ!", Toast.LENGTH_SHORT).show();
            }
        });

        btnTest.setOnClickListener(v -> {
            triggerTestCall();
            dialog.dismiss();
        });

        btnBattery.setOnClickListener(v -> requestIgnoreBatteryOptimization());

        btnClose.setOnClickListener(v -> dialog.dismiss());

        dialog.show();
    }

    private void triggerTestCall() {
        Toast.makeText(this, "🚀 Đang kích hoạt cuộc gọi thử nghiệm...", Toast.LENGTH_SHORT).show();

        // 1. Kích hoạt trực tiếp trên App
        Intent testIntent = new Intent(this, SOCService.class);
        testIntent.putExtra("test_call", true);
        startService(testIntent);

        // 2. Bắn tín hiệu lên Server để đồng bộ Web Dashboard
        new Thread(() -> {
            try {
                String serverUrl = prefs.getString("server_url", DEFAULT_SERVER_URL);
                if (!serverUrl.endsWith("/")) serverUrl += "/";
                URL url = new URL(serverUrl + "api/test_internal_call");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setConnectTimeout(3000);
                conn.getResponseCode();
                conn.disconnect();
            } catch (Exception ignored) {}
        }).start();
    }

    private void requestPermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.POST_NOTIFICATIONS}, 101);
            }
        }
    }

    private void requestIgnoreBatteryOptimization() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (pm != null && !pm.isIgnoringBatteryOptimizations(getPackageName())) {
                Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivity(intent);
            } else {
                Toast.makeText(this, "✅ App đã được cấp quyền chạy ngầm 24/7!", Toast.LENGTH_SHORT).show();
            }
        }
    }

    private void startSOCService() {
        Intent serviceIntent = new Intent(this, SOCService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent);
        } else {
            startService(serviceIntent);
        }
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
