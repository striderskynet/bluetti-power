package com.striderskynet.bluetti;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Servicio en primer plano que lee el equipo cada 5 minutos y actualiza el widget.
 *
 * <p>Se usa un servicio (y no AlarmManager/WorkManager) porque es la única forma
 * fiable de mantener una actualización de 5 minutos sin restricciones de Doze.</p>
 */
public final class PollService extends Service {

    public static final String ACTION_START = "com.striderskynet.bluetti.START";
    public static final String ACTION_STOP = "com.striderskynet.bluetti.STOP";
    public static final String ACTION_REFRESH = "com.striderskynet.bluetti.REFRESH";

    public static final long INTERVAL_MINUTES = 5L;
    private static final String CHANNEL_ID = "bluetti";
    private static final int NOTIFICATION_ID = 1;

    private ScheduledExecutorService executor;
    private boolean scheduled;
    private volatile boolean polling;

    public static void start(Context context) {
        Intent intent = new Intent(context, PollService.class).setAction(ACTION_START);
        startCompat(context, intent);
    }

    public static void stop(Context context) {
        Intent intent = new Intent(context, PollService.class).setAction(ACTION_STOP);
        try {
            context.startService(intent);
        } catch (Exception ignored) {
            // si no está en ejecución no hay nada que parar
        }
    }

    public static void refresh(Context context) {
        Intent intent = new Intent(context, PollService.class).setAction(ACTION_REFRESH);
        startCompat(context, intent);
    }

    private static void startCompat(Context context, Intent intent) {
        if (Build.VERSION.SDK_INT >= 26) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
        executor = Executors.newSingleThreadScheduledExecutor(new java.util.concurrent.ThreadFactory() {
            @Override
            public Thread newThread(Runnable runnable) {
                Thread thread = new Thread(runnable, "bluetti-poll");
                thread.setDaemon(true);
                return thread;
            }
        });
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ACTION_START : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            Prefs.setEnabled(this, false);
            stopForeground(true);
            stopSelf();
            return START_NOT_STICKY;
        }

        Prefs.setEnabled(this, true);
        startForegroundCompat();
        if (ACTION_REFRESH.equals(action)) {
            runPoll();
        }
        schedule();
        return START_STICKY;
    }

    private void startForegroundCompat() {
        Notification notification = buildNotification(Prefs.loadReading(this));
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    private synchronized void schedule() {
        if (scheduled || executor == null || executor.isShutdown()) {
            return;
        }
        scheduled = true;
        executor.scheduleWithFixedDelay(new Runnable() {
            @Override
            public void run() {
                runPoll();
            }
        }, 0L, INTERVAL_MINUTES, TimeUnit.MINUTES);
    }

    private void runPoll() {
        if (polling) {
            return;
        }
        polling = true;
        try {
            Reading reading = BluettiClient.readNow(this);
            WidgetProvider.updateAll(this);
            updateNotification(reading);
        } catch (Exception exc) {
            Logs.log(this, "Error en el sondeo: " + exc);
        } finally {
            polling = false;
        }
    }

    private void updateNotification(Reading reading) {
        try {
            NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager != null) {
                manager.notify(NOTIFICATION_ID, buildNotification(reading));
            }
        } catch (Exception ignored) {
            // sin permiso de notificaciones el servicio sigue funcionando
        }
    }

    private Notification buildNotification(Reading reading) {
        Intent openIntent = new Intent(this, MainActivity.class);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent contentIntent = PendingIntent.getActivity(this, 0, openIntent, flags);

        PendingIntent refreshIntent = PendingIntent.getService(this, 1,
                new Intent(this, PollService.class).setAction(ACTION_REFRESH), flags);
        PendingIntent stopIntent = PendingIntent.getService(this, 2,
                new Intent(this, PollService.class).setAction(ACTION_STOP), flags);

        String text;
        if (reading.ok()) {
            text = reading.percent + "% · " + reading.totalOut() + " W · " + reading.state()
                    + (reading.demo ? " · demo" : "");
        } else if (reading.error != null) {
            text = "Sin conexión: " + reading.error;
        } else {
            text = "Sin datos todavía";
        }

        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        builder.setSmallIcon(R.drawable.ic_stat)
                .setContentTitle("BLUETTI · actualización cada 5 min")
                .setContentText(text)
                .setContentIntent(contentIntent)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false);
        builder.addAction(0, "Actualizar", refreshIntent);
        builder.addAction(0, "Detener", stopIntent);
        return builder.build();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < 26) {
            return;
        }
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, getString(R.string.notification_channel), NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(getString(R.string.notification_channel_desc));
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
    }

    @Override
    public void onDestroy() {
        if (executor != null) {
            executor.shutdownNow();
            executor = null;
        }
        scheduled = false;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
