# -*- coding: utf-8 -*-
#
# Copyright (C) 2005-2009 Edgewall Software
# Copyright (C) 2005-2007 Christopher Lenz <cmlenz@gmx.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.

from ConfigParser import ConfigParser
from copy import deepcopy
from inspect import cleandoc
import os.path

from .core import ExtensionPoint

__all__ = ['Configuration', 'ConfigSection', 'Option', 'BoolOption',
           'IntOption', 'FloatOption', 'ListOption',
           'OrderedExtensionsOption']

_use_default = object()


def as_bool(value):
    """Convert the given value to a `bool`.

    If `value` is a string, return `True` for any of "yes", "true", "enabled",
    "on" or non-zero numbers, ignoring case. For non-string arguments, return
    the argument converted to a `bool`, or `False` if the conversion fails.
    """
    if isinstance(value, basestring):
        try:
            return bool(float(value))
        except ValueError:
            return value.strip().lower() in ('yes', 'true', 'enabled', 'on')
    try:
        return bool(value)
    except (TypeError, ValueError):
        return False


def to_unicode(text, charset=None):
    """Convert input to an `unicode` object.

    For a `str` object, we'll first try to decode the bytes using the given
    `charset` encoding (or UTF-8 if none is specified), then we fall back to
    the latin1 encoding which might be correct or not, but at least preserves
    the original byte sequence by mapping each byte to the corresponding
    unicode code point in the range U+0000 to U+00FF.

    For anything else, a simple `unicode()` conversion is attempted,
    with special care taken with `Exception` objects.
    """
    if isinstance(text, str):
        try:
            return unicode(text, charset or 'utf-8')
        except UnicodeDecodeError:
            return unicode(text, 'latin1')
    elif isinstance(text, Exception):
        # two possibilities for storing unicode strings in exception data:
        try:
            # custom __str__ method on the exception (e.g. PermissionError)
            return unicode(text)
        except UnicodeError:
            # unicode arguments given to the exception (e.g. parse_date)
            return ' '.join([to_unicode(arg) for arg in text.args])
    return unicode(text)


def _to_utf8(basestr):
    return to_unicode(basestr, 'utf-8').encode('utf-8')


class Configuration(object):
    """Thin layer over `ConfigParser` from the Python standard library.

    In addition to providing some convenience methods, the class remembers
    the last modification time of the configuration file, and reparses it
    when the file has changed.
    """
    def __init__(self, filename, params={}):
        self.filename = filename
        self.parser = ConfigParser()
        self.parser.optionxform = str
        self._old_sections = {}
        self.parents = []
        self._lastmtime = 0
        self._sections = {}
        self.parser.read(filename)

    def __contains__(self, name):
        """Return whether the configuration contains a section of the given
        name.
        """
        return name in self.sections()

    def __getitem__(self, name):
        """Return the configuration section with the specified name."""
        if name not in self._sections:
            self._sections[name] = Section(self, name)
        return self._sections[name]

    def __repr__(self):
        return '<%s %r>' % (self.__class__.__name__, self.filename)

    def get(self, section, key, default=''):
        """Return the value of the specified option.

        Valid default input is a string. Returns a string.
        """
        return self[section].get(key, default)

    def getbool(self, section, key, default=''):
        """Return the specified option as boolean value.

        If the value of the option is one of "yes", "true", "enabled", "on",
        or "1", this method wll return `True`, otherwise `False`.

        Valid default input is a string or a bool. Returns a bool.
        """
        return self[section].getbool(key, default)

    def getint(self, section, key, default=''):
        """Return the value of the specified option as integer.

        Valid default input is a string or an int. Returns an int.
        """
        return self[section].getint(key, default)

    def getfloat(self, section, key, default=''):
        """Return the value of the specified option as float.

        Valid default input is a string, float or int. Returns a float.
        """
        return self[section].getfloat(key, default)

    def getlist(self, section, key, default='', sep=',', keep_empty=False):
        """Return a list of values that have been specified as a single
        comma-separated option.

        A different separator can be specified using the `sep` parameter. If
        the `keep_empty` parameter is set to `True`, empty elements are
        included in the list.

        Valid default input is a string or a list. Returns a string.
        """
        return self[section].getlist(key, default, sep, keep_empty)

    def getpath(self, section, key, default=''):
        """Return a configuration value as an absolute path.

        Relative paths are resolved relative to the location of this
        configuration file.

        Valid default input is a string. Returns a normalized path.
        """
        return self[section].getpath(key, default)

    def defaults(self, compmgr=None):
        """Returns a dictionary of the default configuration values

        If `compmgr` is specified, return only options declared in components
        that are enabled in the given `ComponentManager`.
        """
        defaults = {}
        for (section, key), option in Option.get_registry(compmgr).items():
            defaults.setdefault(section, {})[key] = option.default
        return defaults

    def options(self, section, compmgr=None):
        """Return a list of `(name, value)` tuples for every option in the
        specified section.

        This includes options that have default values that haven't been
        overridden. If `compmgr` is specified, only return default option
        values for components that are enabled in the given `ComponentManager`.
        """
        return self[section].options(compmgr)

    def remove(self, section, key):
        """Remove the specified option."""
        self[section].remove(key)

    def sections(self, compmgr=None, defaults=True):
        """Return a list of section names.

        If `compmgr` is specified, only the section names corresponding to
        options declared in components that are enabled in the given
        `ComponentManager` are returned.
        """
        sections = set([to_unicode(s) for s in self.parser.sections()])
        for parent in self.parents:
            sections.update(parent.sections(compmgr, defaults=False))
        if defaults:
            sections.update(self.defaults(compmgr))
        return sorted(sections)

    def has_option(self, section, option, defaults=True):
        """Returns True if option exists in section in either the project
        burp.ini or one of the parents, or is available through the Option
        registry.
        """
        section_str = _to_utf8(section)
        if self.parser.has_section(section_str):
            if _to_utf8(option) in self.parser.options(section_str):
                return True
        for parent in self.parents:
            if parent.has_option(section, option, defaults=False):
                return True
        return defaults and (section, option) in Option.registry

    def parse_if_needed(self, force=False):
        if not self.filename or not os.path.isfile(self.filename):
            return False

        changed = False
        modtime = os.path.getmtime(self.filename)

        if force or modtime > self._lastmtime:
            self._sections = {}
            self.parser._sections = {}
            if not self.parser.read(self.filename):
                raise IOError("Error reading '%(file)s', make sure it is "
                              "readable." % (self.filename, ))
            self._lastmtime = modtime
            self._old_sections = deepcopy(self.parser._sections)
            changed = True

        if changed:
            self.parents = []
            if self.parser.has_option('inherit', 'file'):
                for filename in self.parser.get('inherit', 'file').split(','):
                    filename = to_unicode(filename.strip())
                    if not os.path.isabs(filename):
                        filename = os.path.join(os.path.dirname(self.filename),
                                                filename)
                    self.parents.append(Configuration(filename))
        else:
            for parent in self.parents:
                changed |= parent.parse_if_needed(force=force)

        if changed:
            self._cache = {}
        return changed


class Section(object):
    """Proxy for a specific configuration section.

    Objects of this class should not be instantiated directly.
    """
    __slots__ = ['config', 'name', 'overridden', '_cache']

    def __init__(self, config, name):
        self.config = config
        self.name = name
        self.overridden = {}
        self._cache = {}

    def contains(self, key, defaults=True):
        if self.config.parser.has_option(_to_utf8(self.name), _to_utf8(key)):
            return True
        for parent in self.config.parents:
            if parent[self.name].contains(key, defaults=False):
                return True
        return defaults and Option.registry.has_key((self.name, key))

    __contains__ = contains

    def iterate(self, compmgr=None, defaults=True):
        """Iterate over the options in this section.

        If `compmgr` is specified, only return default option values for
        components that are enabled in the given `ComponentManager`.
        """
        options = set()
        name_str = _to_utf8(self.name)
        if self.config.parser.has_section(name_str):
            for option_str in self.config.parser.options(name_str):
                option = to_unicode(option_str)
                options.add(option.lower())
                yield option
        for parent in self.config.parents:
            for option in parent[self.name].iterate(defaults=False):
                loption = option.lower()
                if loption not in options:
                    options.add(loption)
                    yield option
        if defaults:
            for section, option in Option.get_registry(compmgr).keys():
                if section == self.name and option.lower() not in options:
                    yield option

    __iter__ = iterate

    def __repr__(self):
        return '<%s [%s]>' % (self.__class__.__name__, self.name)

    def get(self, key, default=''):
        """Return the value of the specified option.

        Valid default input is a string. Returns a string.
        """
        cached = self._cache.get(key, _use_default)
        if cached is not _use_default:
            return cached
        name_str = _to_utf8(self.name)
        key_str = _to_utf8(key)
        if self.config.parser.has_option(name_str, key_str):
            value = self.config.parser.get(name_str, key_str)
        else:
            for parent in self.config.parents:
                value = parent[self.name].get(key, _use_default)
                if value is not _use_default:
                    break
            else:
                if default is not _use_default:
                    option = Option.registry.get((self.name, key))
                    value = option.default if option else _use_default
                else:
                    value = _use_default
        if value is _use_default:
            return default
        if not value:
            value = u''
        elif isinstance(value, basestring):
            value = to_unicode(value)
        self._cache[key] = value
        return value

    def getbool(self, key, default=''):
        """Return the value of the specified option as boolean.

        This method returns `True` if the option value is one of "yes", "true",
        "enabled", "on", or non-zero numbers, ignoring case. Otherwise `False`
        is returned.

        Valid default input is a string or a bool. Returns a bool.
        """
        return as_bool(self.get(key, default))

    def getint(self, key, default=''):
        """Return the value of the specified option as integer.

        Valid default input is a string or an int. Returns an int.
        """
        value = self.get(key, default)
        if not value:
            return 0
        return int(value)

    def getfloat(self, key, default=''):
        """Return the value of the specified option as float.

        Valid default input is a string, float or int. Returns a float.
        """
        value = self.get(key, default)
        if not value:
            return 0.0
        return float(value)

    def getlist(self, key, default='', sep=',', keep_empty=True):
        """Return a list of values that have been specified as a single
        comma-separated option.

        A different separator can be specified using the `sep` parameter. If
        the `keep_empty` parameter is set to `False`, empty elements are
        omitted from the list.

        Valid default input is a string or a list. Returns a list.
        """
        value = self.get(key, default)
        if not value:
            return []
        if isinstance(value, basestring):
            items = [item.strip() for item in value.split(sep)]
        else:
            items = list(value)
        if not keep_empty:
            items = filter(None, items)
        return items

    def getpath(self, key, default=''):
        """Return the value of the specified option as a path, relative to
        the location of this configuration file.

        Valid default input is a string. Returns a normalized path.
        """
        path = self.get(key, default)
        if not path:
            return default
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(self.config.filename), path)
        return os.path.normcase(os.path.realpath(path))

    def options(self, compmgr=None):
        """Return `(key, value)` tuples for every option in the section.

        This includes options that have default values that haven't been
        overridden. If `compmgr` is specified, only return default option
        values for components that are enabled in the given `ComponentManager`.
        """
        for key in self.iterate(compmgr):
            yield key, self.get(key)


def _get_registry(cls, compmgr=None):
    """Return the descriptor registry.

    If `compmgr` is specified, only return descriptors for components that
    are enabled in the given `ComponentManager`.
    """
    if compmgr is None:
        return cls.registry

    from .core import ComponentMeta
    components = {}
    for comp in ComponentMeta._components:
        for attr in comp.__dict__.itervalues():
            if isinstance(attr, cls):
                components[attr] = comp

    return dict(each for each in cls.registry.iteritems()
                if each[1] not in components
                   or compmgr.is_enabled(components[each[1]]))


class ConfigSection(object):
    """Descriptor for configuration sections."""

    registry = {}

    @staticmethod
    def get_registry(compmgr=None):
        """Return the section registry, as a `dict` mapping section names to
        `ConfigSection` objects.

        If `compmgr` is specified, only return sections for components that are
        enabled in the given `ComponentManager`.
        """
        return _get_registry(ConfigSection, compmgr)

    def __init__(self, name, doc, doc_domain='burpini'):
        """Create the configuration section."""
        self.name = name
        self.registry[self.name] = self
        self.__doc__ = cleandoc(doc)
        self.doc_domain = doc_domain

    def __get__(self, instance, owner):
        if instance is None:
            return self
        config = getattr(instance, 'config', None)
        if config and isinstance(config, Configuration):
            return config[self.name]

    def __repr__(self):
        return '<%s [%s]>' % (self.__class__.__name__, self.name)


class Option(object):
    """Descriptor for configuration options."""

    registry = {}
    accessor = Section.get

    @staticmethod
    def get_registry(compmgr=None):
        """Return the option registry, as a `dict` mapping `(section, key)`
        tuples to `Option` objects.

        If `compmgr` is specified, only return options for components that are
        enabled in the given `ComponentManager`.
        """
        return _get_registry(Option, compmgr)

    def __init__(self, section, name, default=None, doc='',
                 doc_domain='burpini'):
        """Create the configuration option.

        :param section: the name of the configuration section this option
            belongs to
        :param name: the name of the option
        :param default: the default value for the option
        :param doc: documentation of the option
        """
        self.section = section
        self.name = name
        self.default = default
        self.registry[(self.section, self.name)] = self
        self.__doc__ = cleandoc(doc)
        self.doc_domain = doc_domain

    def __get__(self, instance, owner):
        if instance is None:
            return self
        config = getattr(instance, 'config', None)
        if config and isinstance(config, Configuration):
            section = config[self.section]
            value = self.accessor(section, self.name, self.default)
            return value

    def __set__(self, instance, value):
        raise AttributeError("can't set attribute")

    def __repr__(self):
        return '<%s [%s] "%s">' % (self.__class__.__name__, self.section,
                                   self.name)


class BoolOption(Option):
    """Descriptor for boolean configuration options."""
    accessor = Section.getbool


class IntOption(Option):
    """Descriptor for integer configuration options."""
    accessor = Section.getint


class FloatOption(Option):
    """Descriptor for float configuration options."""
    accessor = Section.getfloat


class ListOption(Option):
    """Descriptor for configuration options that contain multiple values
    separated by a specific character.
    """

    def __init__(self, section, name, default=None, sep=',', keep_empty=False,
                 doc='', doc_domain='burpini'):
        Option.__init__(self, section, name, default, doc, doc_domain)
        self.sep = sep
        self.keep_empty = keep_empty

    def accessor(self, section, name, default):
        return section.getlist(name, default, self.sep, self.keep_empty)


class OrderedExtensionsOption(ListOption):
    """A comma separated, ordered, list of components implementing `interface`.
    Can be empty.

    If `include_missing` is true (the default) all components implementing
    the interface are returned, with those specified by the option ordered
    first."""

    def __init__(self, section, name, interface, default=None,
                 include_missing=True, doc='', doc_domain='burpini'):
        ListOption.__init__(self, section, name, default, doc=doc,
                            doc_domain=doc_domain)
        self.xtnpt = ExtensionPoint(interface)
        self.include_missing = include_missing

    def __get__(self, instance, owner):
        if instance is None:
            return self
        order = ListOption.__get__(self, instance, owner)
        components = []
        for impl in self.xtnpt.extensions(instance):
            if self.include_missing or impl.__class__.__name__ in order:
                components.append(impl)

        def compare(x, y):
            x, y = x.__class__.__name__, y.__class__.__name__
            if x not in order:
                return int(y in order)
            if y not in order:
                return -int(x in order)
            return cmp(order.index(x), order.index(y))
        components.sort(compare)
        return components
