# -*- coding: utf-8 -*-

# Standard Library Imports
from functools import partial
from binascii import hexlify
import urlparse
import logging
import inspect
import time
import json
import re

# Kodi imports
import xbmcaddon
import xbmcgui
import xbmc

# Package imports
from .support import KodiLogHandler, parse_sysargs, CacheProperty

# Fetch addon data objects
script_data = xbmcaddon.Addon("script.module.codequick")
addon_data = xbmcaddon.Addon()

# The id of the running addon
plugin_id = addon_data.getAddonInfo("id")
logger_id = re.sub("[ .]", "-", addon_data.getAddonInfo("name"))

# Base Logger
kodi_logger = KodiLogHandler()
base_logger = logging.getLogger()
base_logger.addHandler(kodi_logger)
base_logger.propagate = False
base_logger.setLevel(logging.DEBUG)

# Logger specific to this module
logger = logging.getLogger("%s.support" % logger_id)

# Extract calling arguments from sys args
selector, handle, params = parse_sysargs()

# Listing auto sort methods
auto_sort = set()


def unittest_caller(route, *args, **kwargs):
    """
    Function to allow callbacks to be easily called from unittests.
    Parent argument will be auto instantiated and passed to callback.
    This basically acts as a constructor to callback.

    :type route: Route
    :param route: The route path to callback.
    :param args: Positional arguments to pass to callback.
    :param kwargs: Keyword arguments to pass to callback.
    :returns: The response from the callback function.
    """
    # Change the selector to match callback route
    # This will ensure that the plugin paths are currect
    global selector
    org_selector = selector
    selector = route.path

    # Update support params with the params
    # that are to be passed to callback
    if args:
        arg_map = route.args_to_kwargs(args)
        params.update(arg_map)

    if kwargs:
        params.update(kwargs)

    # Instantiate the parent
    controller_ins = route.parent()

    try:
        # Now we are ready to call the callback and return its results
        return route.callback(controller_ins, *args, **kwargs)
    finally:
        # Reset global datasets
        kodi_logger.debug_msgs = []
        selector = org_selector
        auto_sort.clear()
        params.clear()


def build_path(path=None, query=None, **extra_query):
    """
    Build addon url that can be passeed to kodi for kodi to use when calling listitems.
    
    :param path: [opt] The route selector path referencing the callback object. (default: current route selector)
    :param query: [opt] A set of query key/value pairs to add to plugin path.
    :param extra_query: [opt] Keyword arguments if given will be added to the current set of querys.

    :return: Plugin url for kodi.
    :rtype: str
    """

    # If extra querys are given then append to current set of querys
    if extra_query:
        query = params.copy()
        query.update(extra_query)

    # Encode the query parameters using json
    if query:
        query = "_json_=" + hexlify(json.dumps(query))

    # Build url with new query parameters
    return urlparse.urlunsplit(("plugin", plugin_id, path if path else selector, query, ""))


class Route(object):
    """Handle callback route data."""
    __slots__ = ("parent", "callback", "org_callback", "path", "is_playable", "is_folder")

    def __init__(self, parent, callback, org_callback, path):
        self.is_playable = parent.is_playable
        self.is_folder = parent.is_folder
        self.org_callback = org_callback
        self.callback = callback
        self.parent = parent
        self.path = path

    def args_to_kwargs(self, args):
        """
        Convert positional arguments to keyword arguments.

        :param tuple args: List of positional arguments to extract names for.
        :returns: A list of tuples consisten of ('arg name', 'arg value)'.
        :rtype: list
        """
        callback_args = inspect.getargspec(self.callback).args[1:]
        return zip(callback_args, args)


class Dispatcher(object):
    def __init__(self):
        self.registered_routes = {}

    def __getitem__(self, route):
        """:rtype: Route"""
        return self.registered_routes[route]

    def __missing__(self, route):
        raise KeyError("missing required route: '{}'".format(route))

    @property
    def callback(self):
        """
        The original callback function/class.

        Primarily used by 'Listitem.next_page' constructor.
        """
        return self[selector].org_callback

    def register(self, callback, cls):
        """
        Register route callback function

        :param callback: The callback function.
        :param cls: Parent class that will handle the callback, if registering a function.
        :returns: The callback function with extra attributes added, 'route', 'testcall'.
        """
        if callback.__name__.lower() == "root":
            path = callback.__name__.lower()
        else:
            path = "{}/{}".format(callback.__module__.strip("_").replace(".", "/"), callback.__name__).lower()

        if path in self.registered_routes:
            raise ValueError("encountered duplicate route: '{}'".format(path))

        # Register a class callback
        elif inspect.isclass(callback):
            if hasattr(callback, "run"):
                # Set the callback as the parent and the run method as the function to call
                route = Route(callback, callback.run, callback, path)
                # noinspection PyTypeChecker
                callback.testcall = staticmethod(partial(unittest_caller, route))
            else:
                raise NameError("missing required 'run' method for class: '{}'".format(callback.__name__))
        else:
            # Register a function callback
            route = Route(cls, callback, callback, path)
            callback.testcall = partial(unittest_caller, route)

        # Return original function undecorated
        self.registered_routes[path] = route
        callback.route = route
        return callback

    def dispatch(self):
        """Dispatch to selected route path."""
        try:
            # Fetch the controling class and callback function/method
            route = self[selector]
            logger.debug("Dispatching to route: '%s'", selector)
            execute_time = time.time()

            # Initialize controller and execute callback
            controller_ins = route.parent()
            controller_ins.execute_route(route.callback)
        except Exception as e:
            # Log the error in both the gui and the kodi log file
            dialog = xbmcgui.Dialog()
            dialog.notification(e.__class__.__name__, str(e), Script.get_info("icon").encode("utf8"))
            logger.critical(str(e), exc_info=1)
        else:
            from . import start_time
            logger.debug("Route Execution Time: %ims", (time.time() - execute_time) * 1000)
            logger.debug("Total Execution Time: %ims", (time.time() - start_time) * 1000)
            controller_ins.run_metacalls()


class Settings(object):
    """Settings class to handle the getting and setting of addon settings."""

    def __getitem__(self, key):
        """
        Returns the value of a setting as a unicode string.

        :param str key: Id of the setting to access.

        :return: Setting as a unicode string.
        :rtype: unicode
        """
        return addon_data.getSetting(key)

    def __setitem__(self, key, value):
        """
        Set an add-on setting.

        :param str key: Id of the setting.
        :param value: Value of the setting.
        :type value: str or unicode
        """
        # noinspection PyTypeChecker
        addon_data.setSetting(key, value if isinstance(value, basestring) else str(value).lower())

    def get_boolean(self, key, addon_id=None):
        """
        Returns the value of a setting as a boolean.

        :param str key: Id of the setting to access.
        :param str addon_id: (Optional) Id of another addon to extract settings from.

        :raises RuntimeError: If addon_id is given and there is no addon with given id.

        :return: Setting as a boolean.
        :rtype: bool
        """
        setting = self.get(key, addon_id).lower()
        return setting == u"true" or setting == u"1"

    def get_int(self, key, addon_id=None):
        """
        Returns the value of a setting as a integer.

        :param str key: Id of the setting to access.
        :param str addon_id: (Optional) Id of another addon to extract settings from.

        :raises RuntimeError: If addon_id is given and there is no addon with given id.

        :return: Setting as a integer.
        :rtype: int
        """
        return int(self.get(key, addon_id))

    def get_number(self, key, addon_id=None):
        """
        Returns the value of a setting as a float.

        :param str key: Id of the setting to access.
        :param str addon_id: (Optional) Id of another addon to extract settings from.

        :raises RuntimeError: If addon_id is given and there is no addon with given id.

        :return: Setting as a float.
        :rtype: float
        """
        return float(self.get(key, addon_id))

    @staticmethod
    def get(key, addon_id=None):
        """
        Returns the value of a setting as a unicode string.

        :param str key: Id of the setting to access.
        :param str addon_id: (Optional) Id of another addon to extract settings from.

        :raises RuntimeError: If addon_id is given and there is no addon with given id.

        :return: Setting as a unicode string.
        :rtype: unicode
        """
        if addon_id:
            return xbmcaddon.Addon(addon_id).getSetting(key)
        else:
            return addon_data.getSetting(key)


class Script(object):
    """
    :cvar INFO: Info logging level.
    :cvar DEBUG: Debug logging level.
    :cvar ERROR: Error logging level.
    :cvar WARNING: Warning logging level.
    :cvar CRITICAL: Critical logging level.
    """
    # Set listing type variables
    is_playable = False
    is_folder = False

    # Dictionary of params passed to callback
    params = params

    # Underlining logger object, for advanced use.
    logger = logging.getLogger(logger_id)

    # Handle the add-on was started with, for advanced use.
    handle = handle

    #: :class:`Settings` Dictionary like object of add-on settings.
    setting = Settings()

    # Logging Levels
    CRITICAL = 50
    WARNING = 30
    ERROR = 40
    DEBUG = 10
    INFO = 20

    @classmethod
    def register(cls, callback):
        """Decorator used to register callback function/class."""
        return dispatcher.register(callback, cls=cls)

    def __init__(self):
        self._title = self.params.get(u"_title_", u"")
        self._callbacks = []

    def execute_route(self, callback):
        """Execute the callback function and process the results."""
        logger.debug("Callback parameters: '%s'", params.callback_params)
        return callback(self, **params.callback_params)

    def register_metacall(self, func, *args, **kwargs):
        """
        Register a callback function that will be executed after kodi's 'endOfDirectory' or 'setResolvedUrl' is called.
        Very useful for fetching extra metadata without slowing down the lising of content.

        :param func: Function that will be called of endOfDirectory.
        :param kwargs: Keyword arguments that will be passed to callback function.
        """
        callback = (func, args, kwargs)
        self._callbacks.append(callback)

    def run_metacalls(self):
        """Execute all callbacks, if any."""
        if self._callbacks:
            # Time before executing callbacks
            start_time = time.time()

            # Execute each callback one by one
            for func, args, kwargs in self._callbacks:
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logger.exception(str(e))

            # Log execution time of callbacks
            logger.debug("Callbacks Execution Time: %ims", (time.time() - start_time) * 1000)

    def log(self, msg, *args, **kwargs):
        """
        Logs a message with logging level 'lvl'.

        Logging Levels:
        DEBUG 	    10
        INFO 	    20
        WARNING 	30
        ERROR 	    40
        CRITICAL 	50

        .. Note::

            When a log level of 50(CRITICAL) is given, then all debug messages that were previously logged
            will now be logged as level 30(WARNING). This will allow for debug messages to show in the normal kodi
            log file when a CRITICAL error has occurred, without having to enable kodi's debug mode.

        :param msg: The message format string.
        :param args: Arguments which are merged into msg using the string formatting operator.
        :param kwargs: Only one keyword argument is inspected: 'lvl', the logging level of the logger.
                       If not given, logging level will default to debug.
        """
        lvl = kwargs.pop("lvl", 10)
        self.logger.log(lvl, msg, *args, **kwargs)

    def notify(self, heading, message, icon=None, display_time=5000, sound=True):
        """
        Send a notification to kodi.

        :param str heading: Dialog heading label.
        :param str message: Dialog message label.
        :param str icon: (Optional) Icon to use. option are 'info', 'error', 'warning'. (default => add-on icon)
        :param int display_time: (Optional) Display_time in milliseconds to show dialog. (default => 5000)
        :param bool sound: (Optional) Whether or not to play notification sound. (default => True)
        """
        if isinstance(heading, unicode):
            heading = heading.encode("utf8")

        if isinstance(message, unicode):
            message = message.encode("utf8")

        if icon and isinstance(icon, unicode):
            icon = icon.encode("utf8")
        elif not icon:
            icon = self.icon.encode("utf8")

        # Send Error Message to Display
        dialog = xbmcgui.Dialog()
        dialog.notification(heading, message, icon, display_time, sound)

    @staticmethod
    def localize(string_id):
        """
        Returns an addon's localized 'unicode string'.

        :param int string_id: The id or reference string to be localized.

        :returns: Localized 'unicode string'.
        :rtype: unicode
        """
        if 30000 <= string_id <= 30999:
            return addon_data.getLocalizedString(string_id)
        elif 32000 <= string_id <= 32999:
            return script_data.getLocalizedString(string_id)
        else:
            return xbmc.getLocalizedString(string_id)

    @staticmethod
    def get_info(key, addon_id=None):
        """
        Returns the value of an addon property as a 'unicode string'.

        :param key: Id of the property to access.
        :param str addon_id: (Optional) Id of another addon to extract properties from.

        :return: Add-on property as a 'unicode string'.
        :rtype: unicode

        :raises RuntimeError: IF no add-on for given id was found.
        """
        # Check if we are extracting data from another add-on
        if addon_id:
            resp = xbmcaddon.Addon(addon_id).getAddonInfo(key)
        elif key == "path_global" or key == "profile_global":
            resp = script_data.getAddonInfo(key[:key.find("_")])
        else:
            resp = addon_data.getAddonInfo(key)

        # Check if path needs to be translated first
        if resp[:10] == "special://":
            resp = xbmc.translatePath(resp)

        # Convert property into unicode
        return unicode(resp, "utf8")

    @CacheProperty
    def icon(self):
        """The add-on's icon image path."""
        return self.get_info("icon")

    @CacheProperty
    def fanart(self):
        """The add-on's fanart image path."""
        return self.get_info("fanart")

    @CacheProperty
    def profile(self):
        """The add-on's profile data directory path."""
        return self.get_info("profile")

    @CacheProperty
    def path(self):
        """The add-on's directory path."""
        return self.get_info("path")


# Dispatcher to manage route callbacks
dispatcher = Dispatcher()