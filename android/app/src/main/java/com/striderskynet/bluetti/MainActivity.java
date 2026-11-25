package com.striderskynet.bluetti;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** Pantalla principal: lista de estaciones, ajustes y diagnóstico. */
public final class MainActivity extends Activity {

    public static final String APP_VERSION = "0.4";
    private static final int REQUEST_PERMISSIONS = 10;
    private static final int[] INTERVAL_SECONDS = {60, 120, 300, 600, 900, 1800, 3600};

    private TextView statusHint;
    private TextView appVersion;
    private Spinner intervalSpinner;
    private Button btnService;
    private Button btnAdd;
    private Button btnLogs;
    private Button btnDemo;
    private Button btnAbout;
    private LinearLayout stationsContainer;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean busy;
    private boolean spinnerInitialized;

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            renderStations();
            handler.postDelayed(this, 3000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        statusHint = findViewById(R.id.status_hint);
        appVersion = findViewById(R.id.app_version);
        intervalSpinner = findViewById(R.id.interval_spinner);
        btnService = findViewById(R.id.btn_service);
        btnAdd = findViewById(R.id.btn_add);
        btnLogs = findViewById(R.id.btn_logs);
        btnDemo = findViewById(R.id.btn_demo);
        btnAbout = findViewById(R.id.btn_about);
        stationsContainer = findViewById(R.id.stations_container);

        appVersion.setText("v" + APP_VERSION);
        Logs.log(this, "Bluetti v" + APP_VERSION + " iniciada");

        setupIntervalSpinner();

        btnAdd.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                startScan();
            }
        });
        btnService.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                toggleService();
            }
        });
        btnLogs.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                showLogs();
            }
        });
        btnDemo.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                toggleDemo();
            }
        });
        btnAbout.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                showAbout();
            }
        });

        ensurePermissions();
        updateButtons();
        renderStations();
        WidgetProvider.updateAll(this);
    }

    @Override
    protected void onResume() {
        super.onResume();
        updateButtons();
        renderStations();
        handler.post(ticker);
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(ticker);
        super.onPause();
    }

    // ----------------------------------------------------------- ajustes

    private void setupIntervalSpinner() {
        ArrayAdapter<CharSequence> adapter = ArrayAdapter.createFromResource(
                this, R.array.interval_options, android.R.layout.simple_spinner_item);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        intervalSpinner.setAdapter(adapter);

        int seconds = DeviceStore.intervalSeconds(this);
        int index = 0;
        for (int i = 0; i < INTERVAL_SECONDS.length; i++) {
            if (INTERVAL_SECONDS[i] == seconds) {
                index = i;
                break;
            }
        }
        intervalSpinner.setSelection(index, false);
        intervalSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (!spinnerInitialized) {
                    return;
                }
                int seconds = INTERVAL_SECONDS[position];
                if (seconds == DeviceStore.intervalSeconds(MainActivity.this)) {
                    return;
                }
                DeviceStore.setIntervalSeconds(MainActivity.this, seconds);
                statusHint.setText("Intervalo de actualización: " + (seconds / 60) + " min");
                if (DeviceStore.serviceEnabled(MainActivity.this)) {
                    PollService.refresh(MainActivity.this);
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                spinnerInitialized = true;
            }
        }, 700);
    }

    private void updateButtons() {
        btnService.setText(DeviceStore.serviceEnabled(this)
                ? R.string.service_disable : R.string.service_enable);
        btnDemo.setText(DeviceStore.isDemo(this) ? R.string.demo_disable : R.string.demo_enable);
    }

    // --------------------------------------------------------- estaciones

    private void renderStations() {
        List<Device> devices = DeviceStore.devices(this);
        stationsContainer.removeAllViews();
        LayoutInflater inflater = LayoutInflater.from(this);
        if (devices.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText(R.string.no_stations);
            empty.setTextColor(getColor(R.color.muted));
            empty.setTextSize(12f);
            empty.setPadding(0, 20, 0, 20);
            stationsContainer.addView(empty);
            return;
        }
        for (Device device : devices) {
            View card = inflater.inflate(R.layout.item_station, stationsContainer, false);
            bindCard(card, device);
            stationsContainer.addView(card);
        }
    }

    private void bindCard(View card, final Device device) {
        Reading reading = DeviceStore.state(this, device.id);
        TextView name = card.findViewById(R.id.item_name);
        TextView state = card.findViewById(R.id.item_state);
        TextView address = card.findViewById(R.id.item_address);
        TextView pct = card.findViewById(R.id.item_pct);
        TextView watts = card.findViewById(R.id.item_w);
        TextView updated = card.findViewById(R.id.item_updated);
        TextView breakdown = card.findViewById(R.id.item_breakdown);

        name.setText(device.displayName());
        String model = reading.deviceType != null && !reading.deviceType.isEmpty()
                ? reading.deviceType : device.model();
        address.setText((model.isEmpty() ? "" : model + " · ") + device.address);

        boolean ok = reading.ok();
        state.setText(ok ? (reading.state() + (reading.demo ? " · demo" : "")) : "sin conexión");
        state.setTextColor(getColor(stateColor(reading)));
        pct.setText(ok ? String.valueOf(reading.percent) : "—");
        pct.setTextColor(getColor(ok ? bandColor(reading.percent) : R.color.muted));
        watts.setText(ok ? formatWatts(reading.totalOut()) : "—");
        updated.setText(reading.time > 0 ? timeAgo(reading.time) : "");
        if (ok) {
            int remainingWh = Math.round(reading.percent * device.capacityWh() / 100f);
            breakdown.setText("AC " + Math.max(0, reading.acOut) + " · DC "
                    + Math.max(0, reading.dcOut) + " · in " + reading.totalIn()
                    + " · " + remainingWh + " Wh");
        } else {
            breakdown.setText(reading.error != null ? reading.error : getString(R.string.no_data));
        }

        card.findViewById(R.id.item_read).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                readDevice(device);
            }
        });
        card.findViewById(R.id.item_details).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                showDetails(device);
            }
        });
        card.findViewById(R.id.item_rename).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                showRename(device);
            }
        });
        card.findViewById(R.id.item_remove).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                confirmRemove(device);
            }
        });
    }

    private int stateColor(Reading reading) {
        if (!reading.ok()) {
            return R.color.bad;
        }
        String state = reading.state();
        if (state.contains("cargando") || state.contains("entrada")) {
            return R.color.accent;
        }
        if (state.contains("descargando")) {
            return R.color.good;
        }
        return R.color.muted;
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

    private static String formatWatts(int watts) {
        return String.format(Locale.getDefault(), "%d W", watts);
    }

    private static String timeAgo(long timestamp) {
        long seconds = Math.max(0, (System.currentTimeMillis() - timestamp) / 1000);
        if (seconds < 60) {
            return "hace " + seconds + " s";
        }
        if (seconds < 3600) {
            return "hace " + (seconds / 60) + " min";
        }
        return "hace " + (seconds / 3600) + " h";
    }

    private static String fullTime(long timestamp) {
        return new SimpleDateFormat("dd/MM/yyyy HH:mm:ss", Locale.getDefault()).format(new Date(timestamp));
    }

    // --------------------------------------------------------- acciones

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
                        if (failure != null) {
                            statusHint.setText("Error al escanear: " + failure);
                            return;
                        }
                        showScanResults(found);
                    }
                });
            }
        }, "bluetti-scan").start();
    }

    private void showScanResults(List<BluettiClient.ScanHit> hits) {
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
                .setItems(labels, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        BluettiClient.ScanHit hit = hits.get(which);
                        Device device = DeviceStore.addOrUpdate(MainActivity.this,
                                hit.address, hit.name, hit.encryptedHint);
                        statusHint.setText("Estación añadida: " + device.displayName());
                        renderStations();
                        readDevice(device);
                    }
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void readDevice(final Device device) {
        if (busy) {
            return;
        }
        busy = true;
        statusHint.setText("Leyendo " + device.displayName() + "…");
        new Thread(new Runnable() {
            @Override
            public void run() {
                final Reading reading = BluettiClient.readNow(MainActivity.this, device);
                WidgetProvider.updateForDevice(MainActivity.this, device.id);
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        busy = false;
                        renderStations();
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

    private void showDetails(final Device device) {
        Reading reading = DeviceStore.state(this, device.id);
        StringBuilder text = new StringBuilder();
        String model = reading.deviceType != null && !reading.deviceType.isEmpty()
                ? reading.deviceType : device.model();
        text.append("Modelo: ").append(model.isEmpty() ? "—" : model).append('\n');
        text.append("Nº de serie: ").append(
                reading.serialNumber == null || reading.serialNumber.isEmpty()
                        ? "—" : reading.serialNumber).append('\n');
        text.append("Dirección BLE: ").append(device.address).append('\n');
        text.append("Conexión: ").append(reading.encrypted ? "cifrada" : "sin cifrar").append('\n');
        if (reading.ok()) {
            text.append("Batería: ").append(reading.percent).append(" %\n");
            text.append("Salida AC: ").append(Math.max(0, reading.acOut)).append(" W\n");
            text.append("Salida DC: ").append(Math.max(0, reading.dcOut)).append(" W\n");
            text.append("Salida total: ").append(reading.totalOut()).append(" W\n");
            text.append("Entrada AC: ").append(Math.max(0, reading.acIn)).append(" W\n");
            text.append("Entrada solar: ").append(Math.max(0, reading.dcIn)).append(" W\n");
            text.append("Entrada total: ").append(reading.totalIn()).append(" W\n");
            text.append("Voltaje de red: ").append(
                    reading.acIn > 5 && reading.gridVoltage > 0
                            ? reading.gridVoltage + " V" : "—").append('\n');
            int capacity = device.capacityWh();
            text.append("Capacidad batería: ").append(capacity).append(" Wh\n");
            text.append("Energía restante: ")
                    .append(Math.round(reading.percent * capacity / 100f))
                    .append(" Wh (aprox.)\n");
            text.append("Estado: ").append(reading.state()).append('\n');
            text.append("Última lectura: ").append(fullTime(reading.time))
                    .append(" (").append(timeAgo(reading.time)).append(")\n");
            text.append("Modo demo: ").append(reading.demo ? "sí" : "no");
        } else {
            text.append("Estado: sin conexión\n");
            text.append("Error: ").append(reading.error == null ? "sin datos" : reading.error);
        }

        new AlertDialog.Builder(this)
                .setTitle(device.displayName())
                .setMessage(text.toString())
                .setPositiveButton(R.string.close, null)
                .setNeutralButton("Leer ahora", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        readDevice(device);
                    }
                })
                .show();
    }

    private void showRename(final Device device) {
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        input.setText(device.alias);
        input.setHint(device.model());
        new AlertDialog.Builder(this)
                .setTitle("Nombre de la estación")
                .setView(input)
                .setPositiveButton("Guardar", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        DeviceStore.rename(MainActivity.this, device.id,
                                input.getText().toString().trim());
                        WidgetProvider.updateForDevice(MainActivity.this, device.id);
                        renderStations();
                    }
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void confirmRemove(final Device device) {
        new AlertDialog.Builder(this)
                .setTitle("Quitar estación")
                .setMessage("¿Quitar «" + device.displayName() + "» de la lista?")
                .setPositiveButton("Quitar", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        DeviceStore.remove(MainActivity.this, device.id);
                        WidgetProvider.updateAll(MainActivity.this);
                        renderStations();
                        statusHint.setText("Estación eliminada");
                    }
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void toggleService() {
        if (DeviceStore.serviceEnabled(this)) {
            PollService.stop(this);
            DeviceStore.setServiceEnabled(this, false);
            statusHint.setText(R.string.service_stopped);
            updateButtons();
            return;
        }
        if (DeviceStore.devices(this).isEmpty()) {
            statusHint.setText(R.string.no_stations);
            return;
        }
        if (!hasBluetoothPermissions()) {
            ensurePermissions();
            statusHint.setText(R.string.permissions_missing);
            return;
        }
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ensurePermissions();
            statusHint.setText(R.string.notifications_needed);
            return;
        }
        try {
            PollService.start(this);
            DeviceStore.setServiceEnabled(this, true);
            statusHint.setText(R.string.service_started);
        } catch (Exception exc) {
            statusHint.setText("No se pudo iniciar el servicio: " + exc.getMessage());
        }
        updateButtons();
    }

    private void toggleDemo() {
        boolean demo = !DeviceStore.isDemo(this);
        DeviceStore.setDemo(this, demo);
        statusHint.setText(demo ? R.string.demo_on : R.string.demo_off);
        updateButtons();
        if (demo) {
            refreshAllDevices();
        } else {
            renderStations();
        }
    }

    private void refreshAllDevices() {
        new Thread(new Runnable() {
            @Override
            public void run() {
                List<Device> devices = DeviceStore.devices(MainActivity.this);
                for (Device device : devices) {
                    BluettiClient.readNow(MainActivity.this, device);
                    WidgetProvider.updateForDevice(MainActivity.this, device.id);
                }
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        renderStations();
                    }
                });
            }
        }, "bluetti-refresh-all").start();
    }

    private void showAbout() {
        new AlertDialog.Builder(this)
                .setTitle("Acerca de Bluetti")
                .setMessage("Bluetti v" + APP_VERSION + "\n\n"
                        + "Hecho por Nesty.\n\n"
                        + "App no oficial para estaciones BLUETTI (AC180P y familia V2), "
                        + "de solo lectura.\n"
                        + "Protocolo BLE/MODBUS y handshake cifrado basados en "
                        + "bluetti-bt-lib (MIT, Patrick762) y bluetti_mqtt "
                        + "(warhammerkid, nhurman, jesherman).\n\n"
                        + "Sin relación con BLUETTI.")
                .setPositiveButton(R.string.close, null)
                .show();
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
                .setNeutralButton(R.string.share_logs, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        shareLogs();
                    }
                })
                .setNegativeButton(R.string.clear_logs, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        Logs.clear(MainActivity.this);
                        statusHint.setText("Registro borrado");
                    }
                })
                .show();
    }

    private void shareLogs() {
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setType("text/plain");
        send.putExtra(Intent.EXTRA_SUBJECT, "Registro Bluetti v" + APP_VERSION);
        send.putExtra(Intent.EXTRA_TEXT, Logs.tail(this));
        startActivity(Intent.createChooser(send, getString(R.string.share_logs)));
    }

    // --------------------------------------------------------- permisos

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
            updateButtons();
        }
    }
}
