package devicedrop

import android.app.Application

class DeviceDropApp: Application() {
    val repository by lazy { DropRepository(this) }
}
