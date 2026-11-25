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

import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * Servicio en primer plano que lee todas las estaciones configuradas cada
 * N segundos (mínimo 60) y actualiza notificación y widgets.
 */
public final class PollService extends Service {

    public static final String ACTION_START = "com.striderskynet.bluetti.START";
    public static final String ACTION_STOP = "com.striderskynet.bluetti.STOP";
    public static final String ACTION_REFRESH = "com.striderskynet.bluetti.REFRESH";

    private static final String CHANNEL_ID = "bluetti";
    private static final int NOTIFICATION_ID = 1;

    private ScheduledExecutorService executor;
    private final Object scheduleLock = new Object();
    private ScheduledFuture<?> pending;
    private volatile boolean polling;
    private volatile boolean refreshRequested;

    public static void start(Context context) {
        startCompat(context, new Intent(context, PollService.class).setAction(ACTION_START));
    }

    public static void stop(Context context) {
        try {
            context.startService(new Intent(context, PollService.class).setAction(ACTION_STOP));
        } catch (Exception ignored) {
            // no estaba en ejecución
        }
    }

    public static void refresh(Context context) {
        startCompat(context, new Intent(context, PollService.class).setAction(ACTION_REFRESH));
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
            DeviceStore.setServiceEnabled(this, false);
            stopForeground(true);
            stopSelf();
            return START_NOT_STICKY;
        }

        DeviceStore.setServiceEnabled(this, true);
        startForegroundCompat();
        if (ACTION_REFRESH.equals(action)) {
            refreshNow();
        } else {
            schedule(0L);
        }
        return START_STICKY;
    }

    private void startForegroundCompat() {
        Notification notification = buildNotification(DeviceStore.devices(this));
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    private void schedule(long delayMs) {
        synchronized (scheduleLock) {
            if (executor == null || executor.isShutdown()) {
                return;
            }
            if (pending != null && !pending.isDone()) {
                return;
            }
            pending = executor.schedule(new Runnable() {
                @Override
                public void run() {
                    runCycle();
                }
            }, Math.max(0L, delayMs), TimeUnit.MILLISECONDS);
        }
    }

    /** Adelanta el próximo sondeo (cambio de intervalo o acción "Actualizar"). */
    public void refreshNow() {
        synchronized (scheduleLock) {
            refreshRequested = true;
            if (pending != null) {
                pending.cancel(false);
                pending = null;
            }
        }
        schedule(500L);
    }

    private void runCycle() {
        synchronized (scheduleLock) {
            pending = null;
        }
        if (polling) {
            refreshRequested = true;
            return;
        }
        polling = true;
        refreshRequested = false;
        long started = System.currentTimeMillis();
        List<Device> devices = null;
        try {
            devices = DeviceStore.devices(this);
            if (devices.isEmpty()) {
                Logs.log(this, "Sondeo sin estaciones configuradas");
            } else {
                for (Device device : devices) {
                    Reading reading = BluettiClient.readNow(this, device);
                    WidgetProvider.updateForDevice(this, device.id);
                    Logs.log(this, "Sondeo " + device.displayName() + ": "
                            + (reading.ok() ? reading.percent + "%, " + reading.totalOut() + " W"
                            : String.valueOf(reading.error)));
                }
            }
            updateNotification(devices);
        } catch (Exception exc) {
            Logs.log(this, "Error en el sondeo: " + exc);
        } finally {
            polling = false;
        }

        long interval = DeviceStore.intervalSeconds(this) * 1000L;
        long elapsed = System.currentTimeMillis() - started;
        long delay = refreshRequested ? 500L : Math.max(10000L, interval - elapsed);
        refreshRequested = false;
        schedule(delay);
    }

    private void updateNotification(List<Device> devices) {
        try {
            NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager != null) {
                manager.notify(NOTIFICATION_ID, buildNotification(devices));
            }
        } catch (Exception ignored) {
            // sin permiso de notificaciones el servicio sigue funcionando
        }
    }

    private Notification buildNotification(List<Device> devices) {
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

        int count = devices == null ? 0 : devices.size();
        String title = count > 1 ? "Bluetti · " + count + " estaciones" : "Bluetti";
        String text;
        if (count == 0) {
            text = "Sin estaciones configuradas";
        } else {
            StringBuilder builder = new StringBuilder();
            for (int i = 0; i < devices.size() && i < 2; i++) {
                Device device = devices.get(i);
                Reading reading = DeviceStore.state(this, device.id);
                if (builder.length() > 0) {
                    builder.append("  ·  ");
                }
                builder.append(device.displayName()).append(": ");
                if (reading.ok()) {
                    builder.append(reading.percent).append("% · ").append(reading.totalOut()).append(" W");
                } else {
                    builder.append("sin conexión");
                }
            }
            if (count > 2) {
                builder.append("  ·  +").append(count - 2);
            }
            text = builder.toString();
        }

        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        builder.setSmallIcon(R.drawable.ic_stat)
                .setContentTitle(title)
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
        synchronized (scheduleLock) {
            pending = null;
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
