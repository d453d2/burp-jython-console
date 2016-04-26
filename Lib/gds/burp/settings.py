# -*- coding: utf-8 -*-
'''
gds.burp.settings
~~~~~~~~~~~~~~~~~

Extension setting keys and default values. Used by :class:`BurpExtender` in
:meth:`~burp_extender.BurpExtender.saveExtensionSetting` and
:meth:`~burp_extender.BurpExtender.loadExtensionSetting`.

Modified by DAS @ 30/06/2016

'''

CONFIG_FILENAME = ('jython.config.filename', 'burp.ini')
CONSOLE_CAPTION = ('jython.ui.console.caption', 'Jython Console')
EXTENSION_NAME = ('jython.extension.name', 'Jython Console')
LOG_FILENAME = ('jython.logging.filename', 'jycor_burp.log')
LOG_FORMAT = ('jython.logging.format', '%(asctime)-15s - %(name)s - %(levelname)s - %(message)s')
LOG_LEVEL = ('jython.logging.level', 10)
