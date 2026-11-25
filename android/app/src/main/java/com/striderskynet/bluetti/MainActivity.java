package com.striderskynet.bluetti;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Pantalla principal: estado, búsqueda de equipo y activación del widget/servicio. */
public final class MainActivity extends Activity {

    private static final int REQUEST_PERMISSIONS = 10;

    private TextView deviceLine;
    private TextView statusPct;
    private TextView statusW;
    private TextView statusState;
    private TextView statusUpdated;
    private TextView statusHint;
    private Button btnScan;
    private Button btnRefresh;
    private Button btnService;
    private Button btnDemo;
    private Button btnLogs;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean busy;

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            updateUi();
            handler.postDelayed(this, 2000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        deviceLine = findViewById(R.id.device_line);
        statusPct = findViewById(R.id.status_pct);
        statusW = findViewById(R.id.status_w);
        statusState = findViewById(R.id.status_state);
        statusUpdated = findViewById(R.id.status_updated);
        statusHint = findViewById(R.id.status_hint);
        btnScan = findViewById(R.id.btn_scan);
        btnRefresh = findViewById(R.id.btn_refresh);
        btnService = findViewById(R.id.btn_service);
        btnDemo = findViewById(R.id.btn_demo);
        btnLogs = findViewById(R.id.btn_logs);

        btnScan.setOnClickListener(new android.view.View.OnClickListener() {
            @Override
            public void onClick(android.view.View view) {
                startScan();
            }
        });
        btnRefresh.setOnClickListener(new android.view.View.OnClickListener() {
            @Override
            public void onClick(android.view.View view) {
                refreshNow();
            }
        });
        btnService.setOnClickListener(new android.view.View.OnClickListener() {
            @Override
            public void onClick(android.view.View view) {
                toggleService();
            }
        });
        btnLogs.setOnClickListener(new android.view.View.OnClickListener() {
            @Override
            public void onClick(android.view.View view) {
                showLogs();
            }
        });
        btnDemo.setOnClickListener(new android.view.View.OnClickListener() {
            @Override
            public void onClick(android.view.View view) {
                toggleDemo();
            }
        });

        ensurePermissions();
        updateUi();
    }

    @Override
    protected void onResume() {
        super.onResume();
        handler.post(ticker);
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(ticker);
        super.onPause();
    }

    // ------------------------------------------------------------------ UI

    private void updateUi() {
        Reading reading = Prefs.loadReading(this);
        boolean configured = !Prefs.address(this).isEmpty();

        String name = Prefs.name(this);
        deviceLine.setText(configured
                ? (name.isEmpty() ? Prefs.address(this) : name + "\n" + Prefs.address(this))
                : getString(R.string.no_device));

        if (reading.ok()) {
            statusPct.setText(String.valueOf(reading.percent));
            statusPct.setTextColor(getColor(bandColor(reading.percent)));
            statusW.setText(String.format(Locale.getDefault(), "%d W", reading.totalOut()));
            statusState.setText(reading.state()
                    + (reading.encrypted ? " · BLE cifrado" : "")
                    + (reading.demo ? " · demo" : ""));
            statusUpdated.setText("Actualizado " + relativeTime(reading.time));
        } else {
            statusPct.setText("—");
            statusPct.setTextColor(getColor(R.color.muted));
            statusW.setText("—");
            statusState.setText(reading.error != null ? reading.error : getString(R.string.no_data));
            statusUpdated.setText(reading.time > 0 ? "Última lectura " + relativeTime(reading.time) : "");
        }

        btnRefresh.setEnabled((configured || Prefs.isDemo(this)) && !busy);
        btnScan.setEnabled(!busy);
        btnService.setText(Prefs.enabled(this)
                ? R.string.service_disable
                : R.string.service_enable);
        btnDemo.setText(Prefs.isDemo(this) ? R.string.demo_disable : R.string.demo_enable);
    }

    private int bandColor(int percent) {
        if (percent >= 50) {
            return R.color.good;
        }
        if (percent >= 20) {
            return R.color.warn;
        }
        return R.color.bad;
    }

    private static String relativeTime(long timestamp) {
        long seconds = Math.max(0, (System.currentTimeMillis() - timestamp) / 1000);
        if (seconds < 60) {
            return "hace " + seconds + " s";
        }
        if (seconds < 3600) {
            return "hace " + (seconds / 60) + " min";
        }
        return "hace " + (seconds / 3600) + " h";
    }

    // ----------------------------------------------------------- acciones

    private void startScan() {
        if (!hasBluetoothPermissions()) {
            ensurePermissions();
            return;
        }
        if (busy) {
            return;
        }
        busy = true;
        statusHint.setText(R.string.scanning);
        updateUi();
        new Thread(new Runnable() {
            @Override
            public void run() {
                List<BluettiClient.ScanHit> hits = null;
                String error = null;
                try {
                    hits = BluettiClient.scan(MainActivity.this, 8000);
                } catch (Exception exc) {
                    error = exc.getMessage();
                }
                final List<BluettiClient.ScanHit> found = hits;
                final String failure = error;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        busy = false;
                        updateUi();
                        if (failure != null) {
                            statusHint.setText("Error al escanear: " + failure);
                            return;
                        }
                        showDevices(found);
                    }
                });
            }
        }, "bluetti-scan").start();
    }

    private void showDevices(List<BluettiClient.ScanHit> hits) {
        if (hits == null || hits.isEmpty()) {
            statusHint.setText(R.string.scan_empty);
            return;
        }
        String[] labels = new String[hits.size()];
        for (int i = 0; i < hits.size(); i++) {
            labels[i] = hits.get(i).label();
        }
        new AlertDialog.Builder(this)
                .setTitle(R.string.choose_device)
                .setItems(labels, new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface dialog, int which) {
                        BluettiClient.ScanHit hit = hits.get(which);
                        Prefs.setDevice(MainActivity.this, hit.address, hit.name, hit.encryptedHint);
                        statusHint.setText("Equipo guardado: " + hit.name);
                        updateUi();
                        refreshNow();
                    }
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void refreshNow() {
        if (Prefs.address(this).isEmpty() && !Prefs.isDemo(this)) {
            statusHint.setText(R.string.no_device);
            return;
        }
        if (!hasBluetoothPermissions()) {
            ensurePermissions();
            return;
        }
        if (busy) {
            return;
        }
        busy = true;
        statusHint.setText(R.string.reading);
        updateUi();
        new Thread(new Runnable() {
            @Override
            public void run() {
                final Reading reading = BluettiClient.readNow(MainActivity.this);
                WidgetProvider.updateAll(MainActivity.this);
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        busy = false;
                        updateUi();
                        if (reading.ok()) {
                            statusHint.setText("Lectura correcta: " + reading.percent + "% · "
                                    + reading.totalOut() + " W");
                        } else {
                            statusHint.setText("No se pudo leer: " + reading.error);
                        }
                    }
                });
            }
        }, "bluetti-read").start();
    }

    private void toggleService() {
        if (Prefs.enabled(this)) {
            PollService.stop(this);
            Prefs.setEnabled(this, false);
            statusHint.setText(R.string.service_stopped);
            updateUi();
            return;
        }
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ensurePermissions();
            statusHint.setText(R.string.notifications_needed);
            return;
        }
        if (!Prefs.isDemo(this) && !hasBluetoothPermissions()) {
            ensurePermissions();
            statusHint.setText(R.string.permissions_missing);
            return;
        }
        try {
            PollService.start(this);
            Prefs.setEnabled(this, true);
            statusHint.setText(R.string.service_started);
        } catch (Exception exc) {
            statusHint.setText("No se pudo iniciar el servicio: " + exc.getMessage());
        }
        updateUi();
    }

    private void toggleDemo() {
        boolean demo = !Prefs.isDemo(this);
        Prefs.setDemo(this, demo);
        statusHint.setText(demo ? R.string.demo_on : R.string.demo_off);
        updateUi();
        if (demo) {
            refreshNow();
        }
    }

    private void showLogs() {
        TextView text = new TextView(this);
        text.setText(Logs.tail(this));
        text.setTextSize(10f);
        text.setTypeface(android.graphics.Typeface.MONOSPACE);
        text.setPadding(24, 24, 24, 24);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(text, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        new AlertDialog.Builder(this)
                .setTitle(R.string.logs)
                .setView(scroll)
                .setPositiveButton(R.string.close, null)
                .setNeutralButton(R.string.clear_logs, new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface dialog, int which) {
                        Logs.clear(MainActivity.this);
                        statusHint.setText("Registro borrado");
                    }
                })
                .show();
    }

    // -------------------------------------------------------- permisos

    private List<String> missingPermissions() {
        List<String> needed = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 31) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.BLUETOOTH_SCAN);
            }
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.BLUETOOTH_CONNECT);
            }
        } else if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.ACCESS_FINE_LOCATION);
        }
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.POST_NOTIFICATIONS);
        }
        return needed;
    }

    private boolean hasBluetoothPermissions() {
        if (Build.VERSION.SDK_INT >= 31) {
            return checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED
                    && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED;
        }
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private void ensurePermissions() {
        List<String> needed = missingPermissions();
        if (!needed.isEmpty()) {
            requestPermissions(needed.toArray(new String[0]), REQUEST_PERMISSIONS);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_PERMISSIONS) {
            statusHint.setText(hasBluetoothPermissions() ? "" : getString(R.string.permissions_missing));
            updateUi();
        }
    }
}
