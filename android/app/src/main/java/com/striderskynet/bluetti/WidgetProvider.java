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
import java.util.Locale;

/** Widget de la pantalla de inicio: carga, consumo y estado. */
public final class WidgetProvider extends AppWidgetProvider {

    @Override
    public void onUpdate(Context context, AppWidgetManager appWidgetManager, int[] appWidgetIds) {
        for (int appWidgetId : appWidgetIds) {
            appWidgetManager.updateAppWidget(appWidgetId, buildViews(context));
        }
    }

    /** Actualiza todas las copias del widget (lo llama el servicio tras cada lectura). */
    public static void updateAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, WidgetProvider.class));
        if (ids == null) {
            return;
        }
        for (int id : ids) {
            manager.updateAppWidget(id, buildViews(context));
        }
    }

    private static RemoteViews buildViews(Context context) {
        Reading reading = Prefs.loadReading(context);
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_bluetti);

        boolean ok = reading.ok();
        String percent = reading.percent >= 0 ? reading.percent + "%" : "—";
        int color;
        if (!ok) {
            color = R.color.muted;
        } else if (reading.percent >= 50) {
            color = R.color.good;
        } else if (reading.percent >= 20) {
            color = R.color.warn;
        } else {
            color = R.color.bad;
        }
        views.setTextViewText(R.id.widget_pct, percent);
        views.setTextColor(R.id.widget_pct, context.getColor(color));

        String watts = ok ? reading.totalOut() + " W" : "—";
        views.setTextViewText(R.id.widget_w, watts);

        String state;
        String time = "";
        if (ok) {
            state = reading.state() + (reading.demo ? " · demo" : "");
        } else if (reading.error != null) {
            state = "sin conexión";
        } else {
            state = "sin datos";
        }
        if (reading.time > 0) {
            time = new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date(reading.time));
        }
        views.setTextViewText(R.id.widget_state, state);
        views.setTextViewText(R.id.widget_time, time);

        Intent open = new Intent(context, MainActivity.class);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        views.setOnClickPendingIntent(R.id.widget_root, PendingIntent.getActivity(context, 0, open, flags));
        return views;
    }
}
