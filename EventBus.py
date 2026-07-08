"""EventBus.py - Simple internal pub/sub event bus for SkrobbleDs

Copyright (c) 2026 edooper
All Rights Reserved
See the licence.txt file provided with this software
for full terms and conditions of use
"""
import threading
import traceback
import collections

class EventBus:
    """A simple thread-safe internal event bus"""
    
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure one bus per application"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EventBus, cls).__new__(cls)
                cls._instance._listeners = collections.defaultdict(list)
                cls._instance._bus_lock = threading.Lock()
                cls._instance._logger = None
        return cls._instance

    def set_logger(self, logger):
        """Set the logger instance"""
        self._logger = logger

    def subscribe(self, event_type, callback):
        """Subscribe a callback to an event type"""
        with self._bus_lock:
            if callback not in self._listeners[event_type]:
                self._listeners[event_type].append(callback)

    def unsubscribe(self, event_type, callback):
        """Unsubscribe a callback from an event type"""
        with self._bus_lock:
            if callback in self._listeners[event_type]:
                self._listeners[event_type].remove(callback)

    def emit(self, event_type, **kwargs):
        """Emit an event with given data to all subscribers"""
        # Copy listeners to avoid holding lock during callback execution
        with self._bus_lock:
            callbacks = list(self._listeners.get(event_type, []))
            
        for callback in callbacks:
            try:
                callback(**kwargs)
            except Exception as e:
                tb = traceback.format_exc()
                msg = f"Error in EventBus callback for {event_type}: {e}\n{tb}"
                if self._logger:
                    self._logger.log(msg)
                else:
                    print(msg)