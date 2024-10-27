#
# This file is part of Glances.
#
# SPDX-FileCopyrightText: 2022 Nicolas Hennion <nicolas@nicolargo.com>
#
# SPDX-License-Identifier: LGPL-3.0-only
#

"""Manage the Glances client browser (list of Glances server)."""

import threading

from defusedxml import xmlrpc

from glances.autodiscover import GlancesAutoDiscoverServer
from glances.client import GlancesClient, GlancesClientTransport
from glances.globals import json_loads
from glances.logger import LOG_FILENAME, logger
from glances.outputs.glances_curses_browser import GlancesCursesBrowser
from glances.password_list import GlancesPasswordList as GlancesPassword
from glances.static_list import GlancesStaticServer

# Correct issue #1025 by monkey path the xmlrpc lib
xmlrpc.monkey_patch()


class GlancesClientBrowser:
    """This class creates and manages the TCP client browser (servers list)."""

    def __init__(self, config=None, args=None):
        # Store the arg/config
        self.args = args
        self.config = config
        self.static_server = None
        self.password = None

        # Load the configuration file
        self.load()

        # Start the autodiscover mode (Zeroconf listener)
        if not self.args.disable_autodiscover:
            self.autodiscover_server = GlancesAutoDiscoverServer()
        else:
            self.autodiscover_server = None

        # Init screen
        self.screen = GlancesCursesBrowser(args=self.args)

    def load(self):
        """Load server and password list from the configuration file."""
        # Init the static server list (if defined)
        self.static_server = GlancesStaticServer(config=self.config)

        # Init the password list (if defined)
        self.password = GlancesPassword(config=self.config)

    def get_servers_list(self):
        """Return the current server list (list of dict).

        Merge of static + autodiscover servers list.
        """
        ret = []

        if self.args.browser:
            ret = self.static_server.get_servers_list()
            if self.autodiscover_server is not None:
                ret = self.static_server.get_servers_list() + self.autodiscover_server.get_servers_list()

        return ret

    def __get_uri(self, server):
        """Return the URI for the given server dict."""
        # Select the connection mode (with or without password)
        if server['password'] != "":
            if server['status'] == 'PROTECTED':
                # Try with the preconfigure password (only if status is PROTECTED)
                clear_password = self.password.get_password(server['name'])
                if clear_password is not None:
                    server['password'] = self.password.get_hash(clear_password)
            return 'http://{}:{}@{}:{}'.format(server['username'], server['password'], server['ip'], server['port'])
        return 'http://{}:{}'.format(server['ip'], server['port'])

    def __update_stats(self, server):
        """Update stats for the given server (picked from the server list)"""
        # Get the server URI
        uri = self.__get_uri(server)

        # Try to connect to the server
        t = GlancesClientTransport()
        t.set_timeout(3)

        # Get common stats from Glances server
        try:
            s = xmlrpc.xmlrpc_client.ServerProxy(uri, transport=t)
        except Exception as e:
            logger.warning(f"Client browser couldn't create socket ({e})")
            return server

        # Get the stats
        for column in self.static_server.get_columns():
            server_key = column.get('plugin') + '_' + column.get('field')
            if 'key' in column:
                server_key += '_' + column.get('key')
            try:
                # Value
                v_json = json_loads(s.getPlugin(column['plugin']))
                if 'key' in column:
                    v_json = [i for i in v_json if i[i['key']].lower() == column['key'].lower()][0]
                server[server_key] = v_json[column['field']]
                # Decoration
                d_json = json_loads(s.getPluginView(column['plugin']))
                if 'key' in column:
                    d_json = d_json.get(column['key'])
                server[server_key + '_decoration'] = d_json[column['field']]['decoration']
            except (KeyError, IndexError, xmlrpc.xmlrpc_client.Fault) as e:
                logger.debug(f"Error while grabbing stats form server ({e})")
            except OSError as e:
                logger.debug(f"Error while grabbing stats form server ({e})")
                server['status'] = 'OFFLINE'
            except xmlrpc.xmlrpc_client.ProtocolError as e:
                if e.errcode == 401:
                    # Error 401 (Authentication failed)
                    # Password is not the good one...
                    server['password'] = None
                    server['status'] = 'PROTECTED'
                else:
                    server['status'] = 'OFFLINE'
                logger.debug(f"Cannot grab stats from server ({e.errcode} {e.errmsg})")
            else:
                # Status
                server['status'] = 'ONLINE'

        return server

    def __display_server(self, server):
        """Connect and display the given server"""
        # Display the Glances client for the selected server
        logger.debug(f"Selected server {server}")

        # Connection can take time
        # Display a popup
        self.screen.display_popup('Connect to {}:{}'.format(server['name'], server['port']), duration=1)

        # A password is needed to access to the server's stats
        if server['password'] is None:
            # First of all, check if a password is available in the [passwords] section
            clear_password = self.password.get_password(server['name'])
            if clear_password is None or self.get_servers_list()[self.screen.active_server]['status'] == 'PROTECTED':
                # Else, the password should be enter by the user
                # Display a popup to enter password
                clear_password = self.screen.display_popup(
                    'Password needed for {}: '.format(server['name']), popup_type='input', is_password=True
                )
            # Store the password for the selected server
            if clear_password is not None:
                self.set_in_selected('password', self.password.get_hash(clear_password))

        # Display the Glance client on the selected server
        logger.info("Connect Glances client to the {} server".format(server['key']))

        # Init the client
        args_server = self.args

        # Overwrite connection setting
        args_server.client = server['ip']
        args_server.port = server['port']
        args_server.username = server['username']
        args_server.password = server['password']
        client = GlancesClient(config=self.config, args=args_server, return_to_browser=True)

        # Test if client and server are in the same major version
        if not client.login():
            self.screen.display_popup(
                "Sorry, cannot connect to '{}'\n" "See '{}' for more details".format(server['name'], LOG_FILENAME)
            )

            # Set the ONLINE status for the selected server
            self.set_in_selected('status', 'OFFLINE')
        else:
            # Start the client loop
            # Return connection type: 'glances' or 'snmp'
            connection_type = client.serve_forever()

            try:
                logger.debug("Disconnect Glances client from the {} server".format(server['key']))
            except IndexError:
                # Server did not exist anymore
                pass
            else:
                # Set the ONLINE status for the selected server
                if connection_type == 'snmp':
                    self.set_in_selected('status', 'SNMP')
                else:
                    self.set_in_selected('status', 'ONLINE')

        # Return to the browser (no server selected)
        self.screen.active_server = None

    def __serve_forever(self):
        """Main client loop."""
        # No need to update the server list
        # It's done by the GlancesAutoDiscoverListener class (autodiscover.py)
        # Or define statically in the configuration file (module static_list.py)
        # For each server in the list, grab elementary stats (CPU, LOAD, MEM, OS...)
        thread_list = {}
        while not self.screen.is_end:
            logger.debug(f"Iter through the following server list: {self.get_servers_list()}")
            for v in self.get_servers_list():
                key = v["key"]
                thread = thread_list.get(key, None)
                if thread is None or thread.is_alive() is False:
                    thread = threading.Thread(target=self.__update_stats, args=[v])
                    thread_list[key] = thread
                    thread.start()

            # Update the screen (list or Glances client)
            if self.screen.active_server is None:
                #  Display the Glances browser
                self.screen.update(self.get_servers_list())
            else:
                # Display the active server
                self.__display_server(self.get_servers_list()[self.screen.active_server])

        # exit key pressed
        for thread in thread_list.values():
            thread.join()

    def serve_forever(self):
        """Wrapper to the serve_forever function.

        This function will restore the terminal to a sane state
        before re-raising the exception and generating a traceback.
        """
        try:
            return self.__serve_forever()
        finally:
            self.end()

    def set_in_selected(self, key, value):
        """Set the (key, value) for the selected server in the list."""
        # Static list then dynamic one
        if self.screen.active_server >= len(self.static_server.get_servers_list()):
            self.autodiscover_server.set_server(
                self.screen.active_server - len(self.static_server.get_servers_list()), key, value
            )
        else:
            self.static_server.set_server(self.screen.active_server, key, value)

    def end(self):
        """End of the client browser session."""
        self.screen.end()
