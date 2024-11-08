#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2016 Raoul Thill                       raoul.thill@gmail.com
#  Copyright 2020-2021 Bernd Meiners                Bernd.Meiners@mail.de
#########################################################################
#  This file is part of SmartHomeNG.
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#########################################################################

import logging
import socket

from io import StringIO
from lib.model.smartplugin import *
from lib.item import Items

from .webif import WebInterface

# If a package is needed, which might be not installed in the Python environment,
# import it like this:

try:
    from lxml import etree
    import requests
    REQUIRED_PACKAGE_IMPORTED = True
except:
    REQUIRED_PACKAGE_IMPORTED = False



class Mcast(socket.socket):
    def __init__(self, local_port):
        socket.socket.__init__(self, socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.bind(('', local_port))

    def mcast_add(self, addr):
        self.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                        socket.inet_aton(addr) + socket.inet_aton('0.0.0.0'))


class Yamaha(SmartPlugin):
    PLUGIN_VERSION = "1.0.3"

    def __init__(self, smarthome):
        # Call init code of parent class (SmartPlugin)
        super().__init__()

        from bin.smarthome import VERSION
        if '.'.join(VERSION.split('.', 2)[:2]) <= '1.5':
            self.logger = logging.getLogger(__name__)

        self.logger.info("Init Yamaha")
        self._yamaha_cmds = ['state', 'power', 'input', 'volume', 'mute']
        self._yamaha_ignore_cmds = ['play_info', 'list_info']
        self._yamaha_rxv = {}
        self.sock = None
        self.mcast_addr = "239.255.255.250"
        self.mcast_port = 1900
        self.mcast_buffer = 1024
        self.mcast_service = "urn:schemas-yamaha-com:service:X_YamahaRemoteControl:1"

        # On initialization error use:
        if not REQUIRED_PACKAGE_IMPORTED:
            self._init_complete = False
            return

        # if plugin should start even without web interface
        self.init_webinterface()

    def run(self):
        self.logger.info("Yamaha starting listener")
        try:
            self.sock = Mcast(self.mcast_port)
            self.sock.mcast_add(self.mcast_addr)
        except OSError:
            self.logger.error("Could not create a socket to Yamaha Receiver")
            return

        ## Todo: why not call initialize directly?
        #self.scheduler_trigger('Yamaha', self._initialize)

        ## test to call initialize directly
        if self._initialize():
            self.alive = True

        # Todo
        # need to reconnect when disconnected. Maybe lib/network.py has a solution
        while self.alive:
            data, addr = self.sock.recvfrom(self.mcast_buffer)
            try:
                host, port = addr
            except TypeError:
                pass
            notification = data.decode('utf-8')
            #self.logger.debug("Received '{}' from {}".format(notification,addr))
            if self.mcast_service in notification:
                if host not in list(self._yamaha_rxv.keys()):
                    self.logger.warn("Yamaha received notify from unknown host {}".format(host))
                else:
                    self.logger.info("Yamaha multicast received {} bytes from {}".format(len(data), host))
                    self.logger.debug(data)
                    for line in notification.split('\r\n'):
                        if line.startswith('<'):
                            line = line.split('?>')[1]
                            events = self._return_value(line, 'event')
                            for event in events:
                                if event.lower() in self._yamaha_cmds:
                                    self.logger.info(
                                        "Yamaha need to update the following item \"{}\" for host: {}".format(event,
                                                                                                              host))
                                    self._get_value(event.lower(), host)
                                    if event.lower() == 'volume':
                                        self._get_value('mute', host)
                                elif event.lower() in self._yamaha_ignore_cmds:
                                    self.logger.debug("Yamaha ignoring command {}.".format(event))
                                else:
                                    self.logger.warn("Yamaha unsupported notify command.")
                self.logger.debug("Yamaha sending ack to {}:{}".format(host, port))
                self.sock.sendto(b'ack', addr)
        else:
            if self.sock:
                self.sock.close()
            self.sock = None
            

    def stop(self):
        self.alive = False
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
        except OSError as e:
            self.logger.error("OSError '{}' occurred while stopping plugin".format(e))
        except Exception as e:
            self.logger.error("Unknown error '{}' occurred while stopping plugin".format(e))
        finally:
            self.sock = None

    def _initialize(self):
        try:
            self.logger.debug("initializing current state")
            for yamaha_host, yamaha_cmd in self._yamaha_rxv.items():
                self.logger.debug("Initializing items for host: {}".format(yamaha_host))
                state = self._update_state(yamaha_host)
                self.logger.debug(state)
                for yamaha_cmd, item in yamaha_cmd.items():
                    if yamaha_cmd != 'state':
                        self.logger.debug("Initializing cmd {} for item {}".format(yamaha_cmd, item))
                        value = self._return_value(state, yamaha_cmd)
                        item(value, self.get_shortname())
        except Exception as e:
            self.logger.error("Exception '{}' occurred".format(e))
            return
        self.logger.debug("Yamaha finished initializing current state")
        return True

    def _return_document(self, doc):
        return etree.tostring(doc, xml_declaration=True, encoding='UTF-8', pretty_print=False)

    def _event_notify(self, value, cmd='PUT'):
        """
        Sets the Yamaha device Notification status

        :param value: Set the notification status on if True is given, else to off
        :type value: boolean
        :param cmd: command for notification, defaults to 'PUT'
        :type cmd: str, optional
        :return: XML with command to set the notification status
        :rtype: str
        """
        root = etree.Element('YAMAHA_AV')
        root.set('cmd', cmd)
        system = etree.SubElement(root, 'System')
        misc = etree.SubElement(system, 'Misc')
        event = etree.SubElement(misc, 'Event')
        notice = etree.SubElement(event, 'Notice')
        if value:
            notice.text = 'On'
        else:
            notice.text = 'Off'
        tree = etree.ElementTree(root)
        return self._return_document(tree)

    def _power(self, value, cmd='PUT'):
        root = etree.Element('YAMAHA_AV')
        root.set('cmd', cmd)
        system = etree.SubElement(root, 'Main_Zone')
        power_control = etree.SubElement(system, 'Power_Control')
        power = etree.SubElement(power_control, 'Power')
        if value is True:
            power.text = 'On'
        elif value is False:
            power.text = 'Standby'
        elif value == 'GetParam':
            power.text = value
        tree = etree.ElementTree(root)
        return self._return_document(tree)

    def _input(self, value, cmd='PUT'):
        root = etree.Element('YAMAHA_AV')
        root.set('cmd', cmd)
        system = etree.SubElement(root, 'Main_Zone')
        input = etree.SubElement(system, 'Input')
        input_sel = etree.SubElement(input, 'Input_Sel')
        input_sel.text = value
        tree = etree.ElementTree(root)
        return self._return_document(tree)

    def _volume(self, value, cmd='PUT'):
        root = etree.Element('YAMAHA_AV')
        root.set('cmd', cmd)
        system = etree.SubElement(root, 'Main_Zone')
        volume = etree.SubElement(system, 'Volume')
        level = etree.SubElement(volume, 'Lvl')
        if cmd == 'GET':
            level.text = value
        else:
            val = etree.SubElement(level, 'Val')
            val.text = str(value)
            exponent = etree.SubElement(level, 'Exp')
            exponent.text = '1'
            unit = etree.SubElement(level, 'Unit')
            unit.text = 'dB'
        tree = etree.ElementTree(root)
        return self._return_document(tree)

    def _mute(self, value, cmd='PUT'):
        root = etree.Element('YAMAHA_AV')
        root.set('cmd', cmd)
        system = etree.SubElement(root, 'Main_Zone')
        volume = etree.SubElement(system, 'Volume')
        mute = etree.SubElement(volume, 'Mute')
        if value is True:
            mute.text = 'On'
        elif value is False:
            mute.text = 'Off'
        elif value == 'GetParam':
            mute.text = value
        tree = etree.ElementTree(root)
        return self._return_document(tree)

    def _validate_inputs(self):
        root = etree.Element('YAMAHA_AV')
        root.set('cmd', 'GET')
        system = etree.SubElement(root, 'System')
        state = etree.SubElement(system, 'Config')
        state.text = 'GetParam'
        tree = etree.ElementTree(root)
        return self._return_document(tree)

    def _get_state(self):
        root = etree.Element('YAMAHA_AV')
        root.set('cmd', 'GET')
        system = etree.SubElement(root, 'Main_Zone')
        state = etree.SubElement(system, 'Basic_Status')
        state.text = 'GetParam'
        tree = etree.ElementTree(root)
        return self._return_document(tree)

    def _get_value(self, notify_cmd, yamaha_host):
        yamaha_payload = None
        if notify_cmd == 'power':
            yamaha_payload = self._power('GetParam', cmd='GET')
        elif notify_cmd == 'volume':
            yamaha_payload = self._volume('GetParam', cmd='GET')
        elif notify_cmd == 'mute':
            yamaha_payload = self._mute('GetParam', cmd='GET')
        elif notify_cmd == 'input':
            yamaha_payload = self._input('GetParam', cmd='GET')

        res = self._submit_payload(yamaha_host, yamaha_payload)
        self.logger.debug(res)
        value = self._return_value(res, notify_cmd)
        item = self._yamaha_rxv[yamaha_host][notify_cmd]
        item(value, self.get_shortname())

    def _return_value(self, state, cmd):
        try:
            tree = etree.parse(StringIO(state))
        except Exception:
            return "Invalid data received"
        if cmd == 'input':
            try:
                value = tree.find('Main_Zone/Basic_Status/Input/Input_Sel')
                return value.text
            except:
                value = tree.find('Main_Zone/Input/Input_Sel')
                return value.text
        elif cmd == 'volume':
            try:
                value = tree.find('Main_Zone/Basic_Status/Volume/Lvl/Val')
                return int(value.text)
            except:
                value = tree.find('Main_Zone/Volume/Lvl/Val')
                return int(value.text)
        elif cmd == 'mute':
            try:
                value = tree.find('Main_Zone/Basic_Status/Volume/Mute')
                if value.text == 'On':
                    return True
                elif value.text == 'Off':
                    return False
                return value.text
            except:
                value = tree.find('Main_Zone/Volume/Mute')
                if value.text == 'On':
                    return True
                elif value.text == 'Off':
                    return False
                return value.text
        elif cmd == 'power':
            try:
                value = tree.find('Main_Zone/Basic_Status/Power_Control/Power')
                if value.text == 'Standby':
                    return False
                elif value.text == 'On':
                    return True
            except:
                value = tree.find('Main_Zone/Power_Control/Power')
                if value.text == 'Standby':
                    return False
                elif value.text == 'On':
                    return True
        elif cmd == 'event':
            events = []
            for entry in tree.findall('Main_Zone/Property'):
                events.append(entry.text)
            return events

    def _submit_payload(self, host, payload):
        """
        Creates a data package with payload given as string containing some XML coded command 

        :param host: IP or hostname of Yamaha device
        :type host: str
        :param payload: XML coded command
        :type payload: str
        :return: Returns the response if receiveed by device, otherwise None
        :rtype: str
        """
        if payload:
            self.logger.debug("Sending payload {}".format(payload))
            res = requests.post("http://%s/YamahaRemoteControl/ctrl" % host,
                                headers={
                                    "Accept": "text/xml",
                                    "User-Agent": "SmartHomeNG"
                                },
                                timeout=4,
                                data=payload)
            response = res.text
            del res
            if response == "":
                self.logger.warn("No response received.")
            else:
                self.logger.debug("Response received: '{}'".format(response))
            return response
        else:
            self.logger.warn("No payload given")
            return None

    def _lookup_host(self, item):
        """
        A ``yamaha_cmd`` Item needs the parent to have the attribute ``yamaha_host``
        This method gets the parents ``yamaha_host`` attributes value.

        :param item: Item with a ``yamaha_cmd``
        :type item: item
        :return: Either the ip or hostname of the device or an empty string otherwise
        :rtype: str
        """
        parent = item.return_parent()
        yamaha_host = self.get_iattr_value(parent.conf,'yamaha_host')
        return yamaha_host

    def parse_item(self, item):
        """
        This method is called for every item in SmartHomeNG when the plugin is already initialized.

        :param item:    The item to process.
        :return:        If the plugin needs to be informed of an items change you should return a call back function
                        like the function update_item down below. An example when this is needed is the knx plugin
                        where parse_item returns the update_item function when the attribute knx_send is found.
                        This means that when the items value is about to be updated, the call back function is called
                        with the item, caller, source and dest as arguments and in case of the knx plugin the value
                        can be sent to the knx with a knx write function within the knx plugin.
        """
        if self.has_iattr(item.conf, 'yamaha_cmd'):
            self.logger.debug("parse item: {}".format(item))
            yamaha_host = self._lookup_host(item)
            # todo: abort if yamaha_host is empty
            yamaha_cmd = self.get_iattr_value(item.conf, 'yamaha_cmd').lower()
            if not yamaha_cmd in self._yamaha_cmds:
                self.logger.warning("{} not in valid commands: {}".format(yamaha_cmd, self._yamaha_cmds))
                return None
            else:
                try:
                    self._yamaha_rxv[yamaha_host][yamaha_cmd] = item
                except KeyError:
                    self._yamaha_rxv[yamaha_host] = {}
                    self._yamaha_rxv[yamaha_host][yamaha_cmd] = item
            return self.update_item

    def update_item(self, item, caller=None, source=None, dest=None):
        """
        Item has been updated

        This method is called, if the value of an item has been updated by SmartHomeNG.
        It should write the changed value out to the device (hardware/interface) that
        is managed by this plugin.

        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        """
        if self.alive and caller != self.get_shortname():
            # code to execute if the plugin is not stopped
            # and only, if the item has not been changed by this this plugin:
            self.logger.info("Update item: {}, item has been changed outside this plugin".format(item.property.path))

            yamaha_cmd = self.get_iattr_value(item.conf, 'yamaha_cmd')
            yamaha_host = self._lookup_host(item)
            yamaha_payload = None
            yamaha_notify = False

            if yamaha_cmd == 'power':
                yamaha_payload = self._power(item())
                yamaha_notify = True
            elif yamaha_cmd == 'volume':
                yamaha_payload = self._volume(item())
            elif yamaha_cmd == 'mute':
                yamaha_payload = self._mute(item())
            elif yamaha_cmd == 'input':
                yamaha_payload = self._input(item())

            self._submit_payload(yamaha_host, yamaha_payload)
            self._update_state(yamaha_host)
            if yamaha_notify:
                # When power on, ensure event notify is enabled
                self._submit_payload(yamaha_host, self._event_notify(True))
            return None

    def _update_state(self, yamaha_host):
        state = self._submit_payload(yamaha_host, self._get_state())
        return state

    def init_webinterface(self):
        """"
        Initialize the web interface for this plugin

        This method is only needed if the plugin is implementing a web interface
        """
        try:
            self.mod_http = Modules.get_instance().get_module(
                'http')  # try/except to handle running in a core version that does not support modules
        except:
            self.mod_http = None
        if self.mod_http == None:
            self.logger.error("Not initializing the web interface")
            return False

        import sys
        if not "SmartPluginWebIf" in list(sys.modules['lib.model.smartplugin'].__dict__):
            self.logger.warning("Web interface needs SmartHomeNG v1.5 and up. Not initializing the web interface")
            return False

        # set application configuration for cherrypy
        webif_dir = self.path_join(self.get_plugin_dir(), 'webif')
        config = {
            '/': {
                'tools.staticdir.root': webif_dir,
            },
            '/static': {
                'tools.staticdir.on': True,
                'tools.staticdir.dir': 'static'
            }
        }

        # Register the web interface as a cherrypy app
        self.mod_http.register_webif(WebInterface(webif_dir, self),
                                     self.get_shortname(),
                                     config,
                                     self.get_classname(), self.get_instance_name(),
                                     description='')

        return True
