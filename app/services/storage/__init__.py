from app.services.storage.local_storage import LocalStorage
from app.services.storage.storage import Storage
from app.settings import settings

storage: Storage = LocalStorage(settings.STORAGE_DIR)