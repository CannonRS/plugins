#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
# Copyright 2017 Henning Behrend; Version 2.0
# Copyright 2020 Ronny
#########################################################################
#  This file is part of SmartHomeNG.
#  https://github.com/smarthomeNG/smarthome
#  http://knx-user-forum.de/
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

# Änderungen:
# - BinaryPayloadDecoder: Fehler korrigiert
# - fanSpeed kann jetzt direkt geändert werden
# - activatePowerBoost entfernt
# - fan1rpm und fan2rpm können ausgelesen werden
# - systemid kann ausgelesen werden
# - serialnum kann ausgelesen werden
# - DHCP-Status und IP-Adressen können ausgelesen werden
# - bypassstate liefert jetzt True und False, anstatt Texte zurück
# - prmRamIdxUnitMode, anstatt nach == zu prüfen, wird mit & geprüft
# - prmRamIdxUnitMode liefert jetzt Zahlenwert zurück
# - diverse Änderungen
import time
import threading
import logging
from lib.model.smartplugin import SmartPlugin

# import pydevd

# pymodbus library from https://code.google.com/p/pymodbus/
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.payload import BinaryPayloadBuilder

class PluggitException(Exception):
    pass

class Pluggit(SmartPlugin):
    ALLOW_MULTIINSTANCE = False
    PLUGIN_VERSION="1.2.3"

    _myTempReadDict = {}
    _myTempWriteDict = {}
    #============================================================================#
    # define variables for most important modbus registers of KWL "Pluggit AP310"
    #
    # Important: In the PDU Registers are addressed starting at zero.
    # Therefore registers numbered 1-16 are addressed as 0-15.
    # that means e.g. holding register "40169" is "40168" and so on
    #============================================================================#

    # dictionary for modbus registers
    _modbusRegisterDic = {
        'prmSystemID': 2,                       # 40003: system information
        'prmSystemSerialNum': 4,                # 40005: system serial
        #'prmSystemName': 8,                     # 40009: system name
        'prmFWVersion': 24,                     # 40025: firmware version
        'prmDHCPEN': 26,                        # 40027: DHCP enable
        'prmCurrentIPAddress': 28,              # 40029: current IP-Adress
        'prmCurrentIPMask': 32,                 # 40033: current IP-Mask
        'prmCurrentIPGateway': 36,              # 40037: current IP-Gateway
        'prmMACAddr': 40,                       # 40041: current MAC-Adress
        'prmDateTime': 108,                     # 40109: Current Date/Time in Unix time (amount of seconds from 1.1.1970)
        'prmHALTaho1': 100,                     # 40101: fan1 rpm
        'prmHALTaho2': 102,                     # 40103: fan2 rpm
        'prmDateTimeSet': 110,                  # 40111: set current Date/Time in Unix time (amount of seconds from 1.1.1970)
        'prmRamIdxT1': 132,                     # 40133: T1, °C, Frischluft
        'prmRamIdxT2': 134,                     # 40135: T2, °C, Zuluft
        'prmRamIdxT3': 136,                     # 40137: T3, °C, Abluft
        'prmRamIdxT4': 138,                     # 40139: T4, °C, Fortluft
        # 'prmRamIdxT5': 140,                   # 40141: T5, °C
        'prmRamIdxUnitMode': 168,               # 40169: Active Unit mode> 0x0004 Manual Mode; 0x0008 WeekProgram
        'prmRamIdxBypassActualState': 198,      # 40199: Bypass state: Closed 0x0000; In process 0x0001; Closing 0x0020; Opening 0x0040; Opened 0x00FF -> opened = summer
        'prmRamIdxBypassManualTimeout': 264,    # 40265: Manual bypass duration in minutes
        'prmRomIdxSpeedLevel': 324,             # 40325: Speed level of Fans in Manual mode; shows a current speed level [4-0]; used for changing of the fan speed level
        # 'prmVOC': 430,                        # 40431: VOC sensor value (read from VOC); ppm. If VOC is not installed, then 0.
        'prmBypassTmin': 444,                   # 40445: Minimum temperature of Bypass openning (°C), if T1 < Tmin then bypass should be closed
        'prmBypassTmax': 446,                   # 40447: Maximum temperature of Bypass openning (°C), if T1 > Tmax or Tmax is 0 then bypass should be closed
        'prmNumOfWeekProgram': 466,             # 40467: Number of the Active Week Program (for Week Program mode)
        'prmFilterRemainingTime': 554,          # 40555: Remaining time of the Filter Lifetime (Days)
        'prmWorkTime': 624,                     # 40625: Work time of system, in hours
        'prmStartExploitationDateStamp': 668    # 40669: installation date/time in UNIX format
    }

    # Initialize connection
    def __init__(self, smarthome, host, port=502, cycle=50):
        self.logger = logging.getLogger(__name__)
        self._host = host
        self._port = int(port)
        self._sh = smarthome
        self._cycle = int(cycle)
        self._lock = threading.Lock()
        self._is_connected = False
        self._items = {}
        self.connect()
        # pydevd.settrace("10.20.0.125")

    def connect(self):
        start_time = time.time()
        if self._is_connected:
            return True
        self._lock.acquire()
        try:
            self.logger.info("Pluggit: connecting to {0}:{1}".format(self._host, self._port))
            self._Pluggit = ModbusTcpClient(self._host, self._port)
        except Exception as e:
            self.logger.error("Pluggit: could not connect to {0}:{1}: {2}".format(self._host, self._port, e))
            return
        finally:
            self._lock.release()
        self.logger.info("Pluggit: connected to {0}:{1}".format(self._host, self._port))
        self._is_connected = True
        end_time = time.time()
        self.logger.debug("Pluggit: connection took {0} seconds".format(end_time - start_time))

    def disconnect(self):
        start_time = time.time()
        if self._is_connected:
            try:
                self._Pluggit.close()
            except:
                pass
        self._is_connected = False
        end_time = time.time()
        self.logger.debug("Pluggit: disconnect took {0} seconds".format(end_time - start_time))

    def run(self):
        self.alive = True
        self._sh.scheduler.add('Pluggit', self._refresh, cycle=self._cycle)

    def stop(self):
        self.alive = False

    # parse items in pluggit.conf
    def parse_item(self, item):
        # check for smarthome.py attribute 'pluggit_listen' in pluggit.conf
        if self.has_iattr(item.conf, 'pluggit_listen'):
            self.logger.debug("Pluggit: parse read item: {0}".format(item))
            pluggit_key = self.get_iattr_value(item.conf, 'pluggit_listen')
            if pluggit_key in self._modbusRegisterDic:
                self._myTempReadDict[pluggit_key] = item
                self.logger.debug("Pluggit: Inhalt des dicts _myTempReadDict nach Zuweisung zu item: '{0}'".format(self._myTempReadDict))
            else:
                self.logger.warn("Pluggit: invalid key {0} configured".format(pluggit_key))
        # check for smarthome.py attribute 'pluggit_send' in pluggit.conf
        if self.has_iattr(item.conf, 'pluggit_send'):
            self.logger.debug("Pluggit: parse send item: {0}".format(item))
            pluggit_sendKey = self.get_iattr_value(item.conf, 'pluggit_send')
            if pluggit_sendKey is None:
                return None
            else:
                self._myTempWriteDict[pluggit_sendKey] = item
                self.logger.debug("Pluggit: Inhalt des dicts _myTempWriteDict nach Zuweisung zu send item: '{0}'".format(self._myTempWriteDict))
                return self.update_item
        else:
            return None

    def parse_logic(self, logic):
        pass

    def update_item(self, item, caller=None, source=None, dest=None):
        if caller != 'Pluggit':
            if self.has_iattr(item.conf, 'pluggit_send'):
                command = self.get_iattr_value(item.conf, 'pluggit_send')
                value = item()
                self.logger.info("Pluggit: {0} set {1} to {2} for {3}".format(caller, command, value, item.property.path))
                if (command == 'prmDateTimeSet') and (isinstance(value, int)):
                    self._setDateTime(value)
                if (command == 'prmRamIdxUnitMode') and (isinstance(value, int)):
                    self._setUnitMode(value)
                if (command == 'prmRomIdxSpeedLevel') and (isinstance(value, int)):
                    self._setFanSpeedLevel(value)
            pass

    # TODO: 32bit
    def _setDateTime(self, date_time):
      
        self.logger.debug("Pluggit: Start => set DateTime: {0}".format(date_time))
        self._Pluggit.write_registers(self._modbusRegisterDic['prmDateTimeSet'], date_time)
        self.logger.debug("Pluggit: Finished => set DateTime: {0}".format(date_time))

    def _setUnitMode(self, unit_mode_value):
      
        self.logger.debug("Pluggit: Start => Write to unit moden: {0}".format(unit_mode_value))
        self._Pluggit.write_registers(self._modbusRegisterDic['prmRamIdxUnitMode'], unit_mode_value)
        self.logger.debug("Pluggit: Finished => Write to unit mode: {0}".format(unit_mode_value))

    def _setFanSpeedLevel(self, fan_speed_level):

        active_unit_mode_value = 4, 0
        fan_speed_level_value = fan_speed_level, 0

        # Change Unit Mode to manual
        self.logger.debug("Pluggit: Start => Change Unit mode to manual: {0}".format(active_unit_mode_value))
        self._Pluggit.write_registers(self._modbusRegisterDic['prmRamIdxUnitMode'], active_unit_mode_value)
        self.logger.debug("Pluggit: Finished => Change Unit mode to manual: {0}".format(active_unit_mode_value))

        # wait 500ms before changing fan speed
        self.logger.debug("Pluggit: Wait 500ms before changing fan speed")
        time.sleep(0.5)

        # Change Fan Speed
        self.logger.debug("Pluggit: Start => Change Fan Speed to Level {0}".format(fan_speed_level))
        self._Pluggit.write_registers(self._modbusRegisterDic['prmRomIdxSpeedLevel'], fan_speed_level_value)
        self.logger.debug("Pluggit: Finished => Change Fan Speed to Level {0}".format(fan_speed_level))

        # self._refresh()
        # check new active unit mode
        active_unit_mode = self._Pluggit.read_holding_registers(self._modbusRegisterDic['prmRamIdxUnitMode'], read_qty = 1).getRegister(0)

        if active_unit_mode & 8 == 8:
            self.logger.debug("Pluggit: Active Unit Mode: Week program")
        elif active_unit_mode & 4 == 4:
            self.logger.debug("Pluggit: Active Unit Mode: Manual")

        # check new fan speed
        fan_speed_level = self._Pluggit.read_holding_registers(self._modbusRegisterDic['prmRomIdxSpeedLevel'], read_qty = 1).getRegister(0)
        self.logger.debug("Pluggit: Fan Speed: {0}".format(fan_speed_level))

    def _activateWeekProgram(self):

        active_unit_mode_value = 8, 0

        # Change Unit Mode to "Week Program"
        self.logger.debug("Pluggit: Start => Change Unit mode to 'Week Program': {0}".format(active_unit_mode_value))
        self._Pluggit.write_registers(self._modbusRegisterDic['prmRamIdxUnitMode'], active_unit_mode_value)
        self.logger.debug("Pluggit: Finished => Change Unit mode to 'Week Program': {0}".format(active_unit_mode_value))

        # self._refresh()

        # check new active unit mode
        active_unit_mode = self._Pluggit.read_holding_registers(self._modbusRegisterDic['prmRamIdxUnitMode'], read_qty = 1).getRegister(0)

        if active_unit_mode & 8 == 8:
            self.logger.debug("Pluggit: Active Unit Mode: Week program")
        elif active_unit_mode & 4 == 4:
            self.logger.debug("Pluggit: Active Unit Mode: Manual")

        # wait 100ms before checking fan speed
        time.sleep(0.1)

        # check new fan speed
        fan_speed_level = self._Pluggit.read_holding_registers(self._modbusRegisterDic['prmRomIdxSpeedLevel'], read_qty = 1).getRegister(0)
        self.logger.debug("Pluggit: Fan Speed: {0}".format(fan_speed_level))

    def _refresh(self):
        start_time = time.time()
        try:
            myCounter = 1
            for pluggit_key in self._myTempReadDict:
                self.logger.debug("Pluggit: ---------------------------------> Wir sind in der Refresh Schleife")
                values = self._modbusRegisterDic[pluggit_key]
                self.logger.debug("Pluggit: Refresh Schleife: Inhalt von values ist {0}".format(values))
                # 2015-01-07 23:53:08,296 DEBUG    Pluggit      Pluggit: Refresh Schleife: Inhalt von values ist 168 -- __init__.py:_refresh:158
                item = self._myTempReadDict[pluggit_key]
                self.logger.debug("Pluggit: Refresh Schleife: Inhalt von item ist {0}".format(item))
                # 2015-01-07 23:53:08,316 DEBUG    Pluggit      Pluggit: Refresh Schleife: Inhalt von item ist pluggit.unitMode -- __init__.py:_refresh:160

                #=======================================================#
                # read values from pluggit via modbus client registers
                #=======================================================#

                self.logger.debug("Pluggit: ------------------------------------------> Wir sind vor dem Auslesen der Werte")
                registerValue = None
                registerValue = self._Pluggit.read_holding_registers(values, read_qty = 1).getRegister(0)
                self.logger.debug("Pluggit: Read parameter '{0}' with register '{1}': Value is '{2}'".format(pluggit_key, values, registerValue))

                # system id
                if values == self._modbusRegisterDic['prmSystemID']:
                    sid = self._Pluggit.read_holding_registers(values, 2)
                    decodersid = BinaryPayloadDecoder.fromRegisters(sid.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    sid = decodersid.decode_32bit_int()
                    item(sid, 'Pluggit')
                    self.logger.debug("Pluggit: System ID: {0}".format(sid))

                # system serial num
                if values == self._modbusRegisterDic['prmSystemSerialNum']:
                    serialvalues = self._Pluggit.read_holding_registers(values, 4)
                    decodersv = BinaryPayloadDecoder.fromRegisters(serialvalues.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    serialnum = decodersv.decode_64bit_uint()
                    self.logger.debug("Pluggit: System serial number: {0}".format(serialnum))
                    item(serialnum, 'Pluggit')

                # Firmware version
                if values == self._modbusRegisterDic['prmFWVersion']:
                    fw = '{}.{}'.format(registerValue >> 8, registerValue & 255)
                    self.logger.debug("Pluggit: Firmware version: {0}".format(fw))
                    item(fw, 'Pluggit')

                # DHCP enabled
                if values == self._modbusRegisterDic['prmDHCPEN']:
                    if registerValue == 1:
                        self.logger.debug("Pluggit: DHCP enabled")
                        item(True, 'Pluggit')
                    else:
                        self.logger.debug("Pluggit: DHCP disabled")
                        item(False, 'Pluggit')

                # current IP adress
                if values == self._modbusRegisterDic['prmCurrentIPAddress']:
                    ipvalues = self._Pluggit.read_holding_registers(values, 2)
                    ipadress = '{}.{}.{}.{}'.format(ipvalues.registers[1] >> 8, ipvalues.registers[1] & 255, ipvalues.registers[0] >> 8, ipvalues.registers[0] & 255)
                    self.logger.debug("Pluggit: current IP adress: {0}".format(ipadress))
                    item(ipadress, 'Pluggit')

                # current IP mask
                if values == self._modbusRegisterDic['prmCurrentIPMask']:
                    ipvalues = self._Pluggit.read_holding_registers(values, 2)
                    ipmask = '{}.{}.{}.{}'.format(ipvalues.registers[1] >> 8, ipvalues.registers[1] & 255, ipvalues.registers[0] >> 8, ipvalues.registers[0] & 255)
                    self.logger.debug("Pluggit: current IP mask: {0}".format(ipmask))
                    item(ipmask, 'Pluggit')

                # current IP gateway
                if values == self._modbusRegisterDic['prmCurrentIPGateway']:
                    ipvalues = self._Pluggit.read_holding_registers(values, 2)
                    ipgateway = '{}.{}.{}.{}'.format(ipvalues.registers[1] >> 8, ipvalues.registers[1] & 255, ipvalues.registers[0] >> 8, ipvalues.registers[0] & 255)
                    self.logger.debug("Pluggit: current IP adress: {0}".format(ipgateway))
                    item(ipgateway, 'Pluggit')

                # MAC adress
                if values == self._modbusRegisterDic['prmMACAddr']:
                    macvalues = self._Pluggit.read_holding_registers(values, 4)
                    macadress = '{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}'.format(macvalues.registers[0] >> 8, macvalues.registers[0] & 255, macvalues.registers[3] >> 8, macvalues.registers[3] & 255, macvalues.registers[2] >> 8, macvalues.registers[2] & 255)
                    self.logger.debug("Pluggit: MAC adress: {0}".format(macadress))
                    item(macadress, 'Pluggit')

                # date time in UNIX format
                if values == self._modbusRegisterDic['prmDateTime']:
                    dt1 = self._Pluggit.read_holding_registers(values, 2)
                    decoderdt1 = BinaryPayloadDecoder.fromRegisters(dt1.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    dt1 = decoderdt1.decode_32bit_int()
                    self.logger.debug("Pluggit: DateTime: {0}".format(dt1))
                    item(dt1, 'Pluggit')

                # week program: possible values 0-10
                if values == self._modbusRegisterDic['prmNumOfWeekProgram']:
                    registerValue += 1
                    item(registerValue, 'Pluggit')
                    # 2015-01-07 23:53:08,435 DEBUG    Pluggit      Item pluggit.unitMode = 8 via Pluggit None None -- item.py:__update:363
                    self.logger.debug("Pluggit: Week Program Number: {0}".format(registerValue))
                    # 2015-01-07 23:53:08,422 DEBUG    Pluggit      Pluggit: Active Unit Mode: Week program -- __init__.py:_refresh:177

                # active unit mode
                if values == self._modbusRegisterDic['prmRamIdxUnitMode'] and registerValue & 8 == 8:
                    self.logger.debug("Pluggit: Active Unit Mode: Week program")
                    #item('Woche', 'Pluggit')
                if values == self._modbusRegisterDic['prmRamIdxUnitMode'] and registerValue & 4 == 4:
                    self.logger.debug("Pluggit: Active Unit Mode: Manual")
                    #item('Manuell', 'Pluggit')
                if values == self._modbusRegisterDic['prmRamIdxUnitMode']:
                    item(registerValue, 'Pluggit')

                # fan speed
                if values == self._modbusRegisterDic['prmRomIdxSpeedLevel']:
                    self.logger.debug("Pluggit: Fan Speed: {0}".format(registerValue))
                    item(registerValue, 'Pluggit')

                # remaining filter lifetime
                if values == self._modbusRegisterDic['prmFilterRemainingTime']:
                    self.logger.debug("Pluggit: Remaining filter lifetime: {0}".format(registerValue))
                    item(registerValue, 'Pluggit')

                # bypass state
                if values == self._modbusRegisterDic['prmRamIdxBypassActualState'] and registerValue == 255:
                    self.logger.debug("Pluggit: Bypass state: opened")
                    #item('geöffnet', 'Pluggit')
                    item(True, 'Pluggit')
                if values == self._modbusRegisterDic['prmRamIdxBypassActualState'] and registerValue == 0:
                    self.logger.debug("Pluggit: Bypass state: closed")
                    #item('geschlossen', 'Pluggit')
                    item(False, 'Pluggit')

                # Manual bypass duration in minutes
                if values == self._modbusRegisterDic['prmRamIdxBypassManualTimeout']:
                    self.logger.debug("Pluggit: Manual bypass duration in minutes: {0}".format(registerValue))
                    item(registerValue, 'Pluggit')

                # fan speed rpm
                # fan 1
                if values == self._modbusRegisterDic['prmHALTaho1']:
                    f1 = self._Pluggit.read_holding_registers(values, 2, unit=22)
                    decoderf1 = BinaryPayloadDecoder.fromRegisters(f1.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    f1 = decoderf1.decode_32bit_float()
                    f1 = round(f1, 0)
                    self.logger.debug("Pluggit: Drehzahl Lüfter 1: {0}".format(f1))
                    item(f1, 'Pluggit')

                # fan speed rpm
                # fan 2
                if values == self._modbusRegisterDic['prmHALTaho2']:
                    f2 = self._Pluggit.read_holding_registers(values, 2, unit=22)
                    decoderf2 = BinaryPayloadDecoder.fromRegisters(f2.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    f2 = decoderf2.decode_32bit_float()
                    f2 = round(f2, 0)
                    self.logger.debug("Pluggit: Drehzahl Lüfter 2: {0}".format(f2))
                    item(f2, 'Pluggit')

                # Temperatures
                # Frischluft außen
                if values == self._modbusRegisterDic['prmRamIdxT1']:
                    t1 = self._Pluggit.read_holding_registers(values, 2, unit=22)
                    decodert1 = BinaryPayloadDecoder.fromRegisters(t1.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    t1 = decodert1.decode_32bit_float()
                    t1 = round(t1, 2)
                    self.logger.debug("Pluggit: Frischluft außen: {0:4.1f}".format(t1))
                    self.logger.debug("Pluggit: Frischluft außen: {0}".format(t1))
                    item(t1, 'Pluggit')

                # Zuluft innen
                if values == self._modbusRegisterDic['prmRamIdxT2']:
                    t2 = self._Pluggit.read_holding_registers(values, 2, unit=22)
                    decodert2 = BinaryPayloadDecoder.fromRegisters(t2.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    t2 = decodert2.decode_32bit_float()
                    t2 = round(t2, 2)
                    self.logger.debug("Pluggit: Zuluft innen: {0:4.1f}".format(t2))
                    self.logger.debug("Pluggit: Zuluft innen: {0}".format(t2))
                    item(t2, 'Pluggit')

                # Abluft innen
                if values == self._modbusRegisterDic['prmRamIdxT3']:
                    t3 = self._Pluggit.read_holding_registers(values, 2, unit=22)
                    decodert3 = BinaryPayloadDecoder.fromRegisters(t3.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    t3 = decodert3.decode_32bit_float()
                    t3 = round(t3, 2)
                    self.logger.debug("Pluggit: Abluft innen: {0:4.1f}".format(t3))
                    self.logger.debug("Pluggit: Abluft innen: {0}".format(t3))
                    item(t3, 'Pluggit')

                # Fortluft außen
                if values == self._modbusRegisterDic['prmRamIdxT4']:
                    t4 = self._Pluggit.read_holding_registers(values, 2, unit=22)
                    decodert4 = BinaryPayloadDecoder.fromRegisters(t4.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    t4 = decodert4.decode_32bit_float()
                    t4 = round(t4, 2)
                    self.logger.debug("Pluggit: Fortluft außen: {0:4.1f}".format(t4))
                    self.logger.debug("Pluggit: Fortluft außen: {0}".format(t4))
                    item(t4, 'Pluggit')

                # Bypass minimum Temperatur
                if values == self._modbusRegisterDic['prmBypassTmin']:
                    t5 = self._Pluggit.read_holding_registers(values, 2, unit=22)
                    decodert5 = BinaryPayloadDecoder.fromRegisters(t5.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    t5 = decodert5.decode_32bit_float()
                    t5 = round(t5, 2)
                    self.logger.debug("Pluggit: Bypass minimum Temperatur: {0:4.1f}".format(t5))
                    self.logger.debug("Pluggit: Bypass minimum Temperatur: {0}".format(t5))
                    item(t5, 'Pluggit')

                # Bypass maximum Temperatur
                if values == self._modbusRegisterDic['prmBypassTmax']:
                    t6 = self._Pluggit.read_holding_registers(values, 2, unit=22)
                    decodert6 = BinaryPayloadDecoder.fromRegisters(t6.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    t6 = decodert6.decode_32bit_float()
                    t6 = round(t6, 2)
                    self.logger.debug("Pluggit: Bypass maximum Temperatur: {0:4.1f}".format(t6))
                    self.logger.debug("Pluggit: Bypass maximum Temperatur: {0}".format(t6))
                    item(t6, 'Pluggit')

                # start time in hours
                if values == self._modbusRegisterDic['prmWorkTime']:
                    dt2 = self._Pluggit.read_holding_registers(values, 2)
                    decoderdt2 = BinaryPayloadDecoder.fromRegisters(dt2.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    dt2 = decoderdt2.decode_32bit_int()
                    self.logger.debug("Pluggit: WorkTime: {0}".format(dt2))
                    item(dt2, 'Pluggit')

                # installation date/time in UNIX format
                if values == self._modbusRegisterDic['prmStartExploitationDateStamp']:
                    dt3 = self._Pluggit.read_holding_registers(values, 2)
                    decoderdt3 = BinaryPayloadDecoder.fromRegisters(dt3.registers, byteorder=Endian.Big, wordorder=Endian.Little)
                    dt3 = decoderdt3.decode_32bit_int()
                    self.logger.debug("Pluggit: StartExploitation: {0}".format(dt3))
                    item(dt3, 'Pluggit')

                self.logger.debug("Pluggit: ------------------------------------------> Ende der Schleife vor sleep, Durchlauf Nr. {0}".format(myCounter))
                time.sleep(0.1)
                myCounter += 1

        except Exception as e:
            self.logger.error("Pluggit: something went wrong in the refresh function: {0}".format(e))
            return
        end_time = time.time()
        cycletime = end_time - start_time
        self.logger.debug("Pluggit: cycle took {0} seconds".format(cycletime))

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    myplugin = Plugin('Pluggit')
    myplugin.run()
