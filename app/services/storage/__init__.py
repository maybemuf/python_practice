from app.services.storage.storage import Storage
from app.settings import settings
from app.services.storage.local_storage import LocalStorage

storage: Storage = LocalStorage(settings.STORAGE_DIR)