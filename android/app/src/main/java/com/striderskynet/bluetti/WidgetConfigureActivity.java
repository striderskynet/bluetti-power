package com.striderskynet.bluetti;

import android.app.Activity;
import android.app.AlertDialog;
import android.appwidget.AppWidgetManager;
import android.content.DialogInterface;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Toast;

import java.util.List;

/** Se muestra al añadir un widget para elegir a qué estación pertenece. */
public final class WidgetConfigureActivity extends Activity {

    private int appWidgetId = AppWidgetManager.INVALID_APPWIDGET_ID;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setResult(RESULT_CANCELED);
        Intent intent = getIntent();
        if (intent != null) {
            appWidgetId = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID,
                    AppWidgetManager.INVALID_APPWIDGET_ID);
        }
        if (appWidgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            finish();
            return;
        }

        final List<Device> devices = DeviceStore.devices(this);
        if (devices.isEmpty()) {
            Toast.makeText(this, R.string.no_stations_yet, Toast.LENGTH_LONG).show();
            startActivity(new Intent(this, MainActivity.class));
            finish();
            return;
        }

        String[] labels = new String[devices.size()];
        for (int i = 0; i < devices.size(); i++) {
            Device device = devices.get(i);
            labels[i] = device.displayName() + "\n" + device.address;
        }

        new AlertDialog.Builder(this)
                .setTitle(R.string.choose_station_widget)
                .setItems(labels, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        DeviceStore.setWidgetDevice(WidgetConfigureActivity.this,
                                appWidgetId, devices.get(which).id);
                        WidgetProvider.updateAll(WidgetConfigureActivity.this);
                        Intent result = new Intent();
                        result.putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, appWidgetId);
                        setResult(RESULT_OK, result);
                        finish();
                    }
                })
                .setNegativeButton(android.R.string.cancel, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        finish();
                    }
                })
                .setOnCancelListener(new DialogInterface.OnCancelListener() {
                    @Override
                    public void onCancel(DialogInterface dialog) {
                        finish();
                    }
                })
                .show();
    }
}
