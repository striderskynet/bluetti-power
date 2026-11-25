package com.striderskynet.bluetti;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Reanuda el servicio tras reiniciar el móvil si el usuario lo dejó activado. */
public final class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            return;
        }
        if (!DeviceStore.serviceEnabled(context)) {
            return;
        }
        try {
            PollService.start(context);
            Logs.log(context, "Servicio reiniciado tras el arranque");
        } catch (Exception exc) {
            Logs.log(context, "No se pudo reiniciar tras el arranque: " + exc);
        }
    }
}
