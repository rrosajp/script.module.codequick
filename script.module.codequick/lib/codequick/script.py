# -*- coding: utf-8 -*-
from __future__ import absolute_import

# Package imports
import codequick.support as support

__all__ = ["Script"]


class Script(support.Base):
    """
    This class is used to create "Script" callbacks. Script callbacks are callbacks
    that just execute code and return nothing.

    This class is also used as the base for all other types of callbacks i.e.
    :class:`codequick.Route<codequick.route.Route>` and :class:`codequick.Resolver<codequick.resolver.Resolver>`.
    """
    def __init__(self, callback, callback_params):
        super(Script, self).__init__()
        callback.func(self, **callback_params)
