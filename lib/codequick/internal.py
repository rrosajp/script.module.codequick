# -*- coding: utf-8 -*-

# Standard Library Imports
import os

# Kodi Imports
import xbmcgui
import xbmc

# Package imports
from .support import Script
from .storage import PersistentDict
from .api import register_route, Route, dispatcher, custom_route
from .listing import Listitem
from .utils import keyboard

# Prerequisites
ENTER_SEARCH_STRING = 16017
ENTER_NUMBER = 611
REMOVE = 1210
DEFAULT = 571
CUSTOM = 636
SEARCH = 137


@custom_route("SetViewMode")
class ViewModeSelecter(Script):
    """
    Class for displaying list of available skin view modes on the addon setting screen.

    Allowing for the selection of a view mode that will be force when
    displaying listitem content. Works with both video & folder views separately.
    """

    def __init__(self):
        super(ViewModeSelecter, self).__init__()
        self.skin_codes = [(self.localize(DEFAULT).encode("utf8"), "")]
        self.skin_id = xbmc.getSkinDir()
        self.setting_id = ""

    def run(self, mode):
        self.setting_id = "{}.{}.view".format(self.skin_id, mode)
        self.populate_skin_codes(mode)
        selection = self.user_selection()
        if selection is not None:
            self.set_mode(selection)

    def populate_skin_codes(self, view):
        """
        Populate the list of skin codes based to the selected view e.g. 'folder' or 'video'

        :param unicode view: The selected view to list skin codes for.
        """
        # Fetch currently saved setting if it exists
        current_mode = self.setting[self.setting_id]

        # Fetch database of skin codes
        skincode_path = os.path.join(self.get_info("path_global"), u"resources", u"data")
        try:
            database = PersistentDict(u"skincodes.json", data_dir=skincode_path, read_only=True)
        except EnvironmentError:
            self.logger.exception("unable to load skincodes database")
        else:
            # Convert the skin codes into a dict of name:mode pairs
            if self.skin_id in database:
                base = database[self.skin_id].get(view, [])
                base.extend(database[self.skin_id].get(u"both", []))
                for view_data in base:
                    mode = str(view_data[u"mode"])

                    # Localize the name of the skin view mode and append strextra if given
                    viewmode_name = self.localize(view_data[u"id"]) if view_data[u"id"] else u""
                    if u"strextra" in view_data:
                        viewmode_name = u"{} {}".format(viewmode_name, view_data[u"strextra"])

                    # Bold the viewmode if it's the current selected viewmode
                    if current_mode == mode:
                        viewmode_name = u"[B]-{}[/B]".format(viewmode_name)
                        current_mode = u""

                    # Update skin codes list
                    data_tuple = (viewmode_name.strip().encode("utf8"), mode)
                    self.skin_codes.append(data_tuple)
            else:
                self.log("no skin codes found for skin: '%s'", self.skin_id)

        # Add custom option to skin codes
        if current_mode:
            current_mode = current_mode.encode("utf8")
            data_tuple = (self.localize(CUSTOM).encode("utf8"), current_mode)
            self.skin_codes.append(("[B]%s (%s)[/B]" % data_tuple, current_mode))
        else:
            self.skin_codes.append((self.localize(CUSTOM).encode("utf8"), ""))

    def user_selection(self):
        """
        Display list of viewmodes that are available and return user selection.

        :returns: The selected skin mode to use.
        :rtype: unicode
        """
        name_tuple, mode_tuple = zip(*self.skin_codes)
        skin_name = self.get_info("name", self.skin_id)

        # Display List to User
        dialog = xbmcgui.Dialog()
        ret = dialog.select(skin_name, name_tuple)

        # Disable custom viewmode if default was selected
        if ret == 0:
            self.log("Reseting viewmode setting to default")
            return ""

        # Ask for custom viewmode if the last item was selected i.e. Custom
        elif ret == (len(name_tuple) - 1):
            return self.ask_for_id(mode_tuple[ret])

        # Map the selected result to the related view mode
        elif ret > 0:
            return mode_tuple[ret]

    def ask_for_id(self, current_mode):
        """
        Ask the user what custom view mode to use.

        :param str current_mode: The default viewmode custom viewmode if one exists.

        :returns: The new custom viewmode.
        :rtype: unicode
        """
        dialog = xbmcgui.Dialog()
        ret = dialog.numeric(0, self.localize(ENTER_NUMBER), current_mode)
        if ret:
            return unicode(ret)
        else:
            return None

    def set_mode(self, new_mode):
        """
        Save new mode to addon setting

        :param new_mode: The new skin mode to use.
        :type new_mode: str or unicode
        """
        self.log("Saving new viewmode setting: '%s'", new_mode)
        self.setting[self.setting_id] = new_mode


@register_route
class SavedSearches(Route):
    """
    Class used to list all saved searches for the addon that called it.
    Usefull to add search support to addon that will also keep track of previous searches
    Also contains option via context menu to remove old search terms.
    """

    def __init__(self):
        super(SavedSearches, self).__init__()

        # List of current saved searches
        self.search_db = PersistentDict(u"searches.json")

    def run(self, remove=None, search=None, **extras):
        """List all saved searches"""

        # Set update listing to True only when change state of searches
        if remove or search:
            self.update_listing = True

        # Remove term from saved searches if remove argument was passed
        if remove in self.search_db:
            del self.search_db[remove]
            self.search_db.flush()

        # Show search dialog if search argument was passed or if there is no search term saved
        elif not self.search_db or search:
            self.search_dialog(extras["url"])

        # List all saved search terms
        return self.list_terms(dispatcher[extras["route"]], extras)

    def search_dialog(self, url):
        """Show dialog for user to enter a new search term."""
        search_term = keyboard("", self.localize(ENTER_SEARCH_STRING), False)
        if search_term:
            self.search_db[search_term] = url % search_term
            self.search_db.flush()

    def list_terms(self, callback, extras):
        """:rtype: :class:`types.GeneratorType`"""
        # Add search listitem
        search_item = self.listItem()
        search_item.label = u"[B]%s[/B]" % self.localize(SEARCH)
        search_item.set_callback(self, search="true", **extras)
        yield search_item

        # Create Context Menu item requirements
        str_remove = self.localize(REMOVE)

        # Add all saved searches to item list
        for search_term, url in self.search_db.items():
            item = Listitem()
            item.set_label(search_term.title())

            # Creatre Context Menu item for removing search term
            item.context.container(str_remove, self, remove=search_term, **extras)

            # Update params with full url and set the callback
            extras["url"] = url
            item.set_callback(callback, **extras)
            yield item

        # Finished with the search database
        self.search_db.close()
