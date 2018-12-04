# -*- coding: utf-8 -*-
from __future__ import absolute_import

# Standard Library Imports
from hashlib import sha1
import pickle

# Package imports
from codequick.storage import PersistentDict
from codequick.support import dispatcher
from codequick.listing import Listitem
from codequick.utils import keyboard, ensure_unicode
from codequick.route import Route, validate_listitems

# Localized string Constants
ENTER_SEARCH_STRING = 16017
REMOVE = 1210
SEARCH = 137

# Name of the database file
SEARCH_DB = u"_new_searches.pickle"


class Search(object):
    def __init__(self, plugin, extra_params):
        # The saved search persistent storage
        self.db = search_db = PersistentDict(SEARCH_DB)
        plugin.register_delayed(search_db.close)

        # Fetch saved data specific to this session
        session_hash = self.hash_params(extra_params)
        self.data = search_db.setdefault(session_hash, [])

    def __iter__(self):
        return iter(self.data)

    def __contains__(self, item):
        return item in self.data

    def __bool__(self):
        return bool(self.data)

    def __nonzero__(self):
        return bool(self.data)

    def remove(self, item):
        self.data.remove(item)
        self.db.flush()

    def append(self, item):
        self.data.append(item)
        self.db.flush()

    @staticmethod
    def hash_params(data):
        # Convert dict of params into a sorted list of key, value pairs
        sorted_dict = sorted(data.items())

        # Pickle the sorted dict so we can hash the contents
        content = pickle.dumps(sorted_dict, protocol=2)
        return ensure_unicode(sha1(content).hexdigest())


def redirect_search(searchdb, plugin, search_term, extras):
    """
    Checks if searh term returns valid results before adding to saved searches.
    Then directly farward the results to kodi.

    :param Search searchdb: Search DB
    :param Route plugin: Tools related to Route callbacks.
    :param str search_term: The serch term used to search for results.
    :param dict extras: Extra parameters that will be farwarded on to the callback function.
    :return: List if valid search results
    """
    plugin.params[u"_title_"] = title = search_term.title()
    plugin.category = title
    callback_params = extras.copy()
    callback_params["search_query"] = search_term

    # We switch selector to redirected callback to allow next page to work properly
    route = callback_params.pop("_route")
    dispatcher.selector = route

    # Fetch search results from callback
    func = dispatcher.get_route()
    listitems = func(plugin, **callback_params)

    # Check that we have valid listitems
    valid_listitems = validate_listitems(listitems)

    # Add the search term to database and return the list of results
    if valid_listitems:
        if search_term not in searchdb:  # pragma: no branch
            searchdb.append(search_term)

        return valid_listitems
    else:
        # Return False to indicate failure
        return False


def list_terms(searchdb, plugin, extras):
    """
    List all saved searches.

    :param Search searchdb: Search DB
    :param Route plugin: Tools related to Route callbacks.
    :param dict extras: Extra parameters that will be farwarded on to the context.container.

    :returns: A generator of listitems.
    :rtype: :class:`types.GeneratorType`
    """
    # Add listitem for adding new search terms
    search_item = Listitem()
    search_item.label = u"[B]%s[/B]" % plugin.localize(SEARCH)
    search_item.set_callback(saved_searches, search=True, **extras)
    search_item.art.global_thumb("search_new.png")
    yield search_item

    # Set the callback function to the route that was given
    callback_params = extras.copy()
    route = callback_params.pop("_route")
    callback = dispatcher.get_route(route).callback

    # Prefetch the localized string for the context menu lable
    str_remove = plugin.localize(REMOVE)

    # List all saved searches
    for search_term in searchdb:
        item = Listitem()
        item.label = search_term.title()

        # Creatre Context Menu item for removing search term
        item.context.container(saved_searches, str_remove, remove_entry=search_term, **extras)

        # Update params with full url and set the callback
        item.params.update(callback_params, search_query=search_term)
        item.set_callback(callback)
        yield item


@Route.register
def saved_searches(plugin, remove_entry=None, search=False, first_load=False, **extras):
    """
    Class used to list all saved searches for the addon that called it.

    Useful to add search support to addon that will also keep track of previous searches.
    Also contains option via context menu to remove old search terms.

    :param plugin:
    :param remove_entry:
    :param search:
    :param first_load:
    :param extras:
    :return:
    """
    searchdb = Search(plugin, extras)

    # Remove search term from saved searches
    if remove_entry and remove_entry in searchdb:
        searchdb.remove(remove_entry)
        plugin.update_listing = True

    # Show search dialog if search argument is True, or if there is no search term saved
    # First load is used to only allow auto search to work when first loading the saved search container.
    # Fixes an issue when there is no saved searches left after removing them.
    elif search or (first_load and not searchdb):
        search_term = keyboard(plugin.localize(ENTER_SEARCH_STRING))
        if search_term:
            return redirect_search(searchdb, plugin, search_term, extras)
        elif not searchdb:
            return False
        else:
            plugin.update_listing = True

    # List all saved search terms
    return list_terms(searchdb, plugin, extras)
