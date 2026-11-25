package com.striderskynet.bluetti;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.widget.RemoteViews;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** Widget por estación: carga, consumo, estado, desglose y última lectura. */
public final class WidgetProvider extends AppWidgetProvider {

    @Override
    public void onUpdate(Context context, AppWidgetManager appWidgetManager, int[] appWidgetIds) {
        for (int appWidgetId : appWidgetIds) {
            ensureMapping(context, appWidgetId);
            appWidgetManager.updateAppWidget(appWidgetId, buildViews(context, appWidgetId));
        }
    }

    @Override
    public void onDeleted(Context context, int[] appWidgetIds) {
        for (int appWidgetId : appWidgetIds) {
            DeviceStore.removeWidget(context, appWidgetId);
        }
    }

    /** Asigna automáticamente la primera estación a widgets antiguos sin configurar. */
    private static void ensureMapping(Context context, int appWidgetId) {
        if (!DeviceStore.widgetDevice(context, appWidgetId).isEmpty()) {
            return;
        }
        List<Device> devices = DeviceStore.devices(context);
        if (!devices.isEmpty()) {
            DeviceStore.setWidgetDevice(context, appWidgetId, devices.get(0).id);
        }
    }

    public static void updateAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, WidgetProvider.class));
        if (ids == null) {
            return;
        }
        for (int id : ids) {
            ensureMapping(context, id);
            manager.updateAppWidget(id, buildViews(context, id));
        }
    }

    public static void updateForDevice(Context context, String deviceId) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, WidgetProvider.class));
        if (ids == null) {
            return;
        }
        for (int id : ids) {
            ensureMapping(context, id);
            if (deviceId != null && deviceId.equals(DeviceStore.widgetDevice(context, id))) {
                manager.updateAppWidget(id, buildViews(context, id));
            }
        }
    }

    private static RemoteViews buildViews(Context context, int appWidgetId) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_bluetti);
        String deviceId = DeviceStore.widgetDevice(context, appWidgetId);
        Device device = DeviceStore.find(context, deviceId);

        Intent open = new Intent(context, MainActivity.class);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        views.setOnClickPendingIntent(R.id.widget_root,
                PendingIntent.getActivity(context, appWidgetId, open, flags));

        if (device == null) {
            views.setTextViewText(R.id.widget_name, "Bluetti");
            views.setTextViewText(R.id.widget_state, "sin estación");
            views.setTextViewText(R.id.widget_pct, "—");
            views.setTextViewText(R.id.widget_w, "—");
            views.setTextViewText(R.id.widget_updated, "");
            views.setTextViewText(R.id.widget_breakdown, "Añade una estación en la app");
            views.setProgressBar(R.id.widget_bar, 100, 0, false);
            return views;
        }

        Reading reading = DeviceStore.state(context, device.id);
        boolean ok = reading.ok();
        views.setTextViewText(R.id.widget_name, device.displayName());

        int pctColor;
        if (!ok) {
            pctColor = R.color.muted;
        } else if (reading.percent >= 50) {
            pctColor = R.color.good;
        } else if (reading.percent >= 20) {
            pctColor = R.color.warn;
        } else {
            pctColor = R.color.bad;
        }
        views.setTextViewText(R.id.widget_pct, ok ? reading.percent + "%" : "—");
        views.setTextColor(R.id.widget_pct, context.getColor(pctColor));
        views.setTextViewText(R.id.widget_w, ok ? reading.totalOut() + " W" : "—");

        if (ok) {
            views.setTextViewText(R.id.widget_state, reading.state() + (reading.demo ? " · demo" : ""));
            views.setTextColor(R.id.widget_state,
                    context.getColor(reading.demo ? R.color.warn : R.color.accent));
            views.setTextViewText(R.id.widget_breakdown,
                    "AC " + Math.max(0, reading.acOut) + " W · DC " + Math.max(0, reading.dcOut)
                            + " W · entrada " + reading.totalIn() + " W");
        } else {
            views.setTextViewText(R.id.widget_state, reading.error != null ? "sin conexión" : "sin datos");
            views.setTextColor(R.id.widget_state, context.getColor(R.color.bad));
            views.setTextViewText(R.id.widget_breakdown,
                    reading.error != null ? reading.error : "sin datos todavía");
        }
        views.setTextViewText(R.id.widget_updated, reading.time > 0 ? timeAgo(reading.time) : "");
        views.setProgressBar(R.id.widget_bar, 100, ok ? Math.max(0, Math.min(100, reading.percent)) : 0, false);
        return views;
    }

    private static String timeAgo(long timestamp) {
        long seconds = Math.max(0, (System.currentTimeMillis() - timestamp) / 1000);
        if (seconds < 60) {
            return "hace " + seconds + " s";
        }
        if (seconds < 3600) {
            return "hace " + (seconds / 60) + " min";
        }
        return new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date(timestamp));
    }
}
