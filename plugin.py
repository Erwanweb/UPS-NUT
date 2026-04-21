#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
<plugin key="ZZ-UPS-NUT" name="RONELABS - UPS NUT Plugin" author="ErwanBCN" version="1.0.3" externallink="https://ronelabs.com">
    <description>
        <h2>UPS NUT Plugin V1.0.3</h2><br/>
        Easily monitor a UPS in Domoticz through NUT (Network UPS Tools).<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Address" label="NUT Server IP" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="NUT Server Port" width="100px" required="true" default="3493"/>
        <param field="Username" label="UPS Name" width="200px" required="true" default="eaton"/>
        <param field="Mode2" label="Polling Interval (heartbeats of 10s)" width="180px" required="true" default="3"/>
        <param field="Mode3" label="Low Battery Threshold (%)" width="150px" required="true" default="25"/>
        <param field="Mode6" label="Logging Level" width="200px">
            <options>
                <option label="Normal" value="0" default="true"/>
                <option label="Debug - Python Only" value="2"/>
                <option label="Debug - Basic" value="62"/>
                <option label="Debug - All" value="1"/>
            </options>
        </param>
    </params>
</plugin>
"""

import socket
import Domoticz

try:
    from Domoticz import Devices, Parameters
except ImportError:
    pass


class BasePlugin:
    def __init__(self):
        self.debug = False
        self.host = "127.0.0.1"
        self.port = 3493
        self.ups_name = "eaton"
        self.poll_interval = 3   # in heartbeats, with Heartbeat(10) => 30 s
        self.low_battery_threshold = 25
        self.counter = 0

    def onStart(self):
        Domoticz.Log("UPS-NUT Plugin started")

        self.host = Parameters["Address"].strip()
        self.port = int(Parameters["Port"])
        self.ups_name = Parameters["Username"].strip()

        try:
            self.poll_interval = max(1, int(Parameters["Mode2"]))
        except Exception:
            self.poll_interval = 3

        try:
            self.low_battery_threshold = max(1, min(100, int(Parameters["Mode3"])))
        except Exception:
            self.low_battery_threshold = 25

        # setup the appropriate logging level
        try:
            debuglevel = int(Parameters["Mode6"])
        except ValueError:
            debuglevel = 0
            self.loglevel = Parameters["Mode6"]
        if debuglevel != 0:
            self.debug = True
            Domoticz.Debugging(debuglevel)
            DumpConfigToLog()
        else:
            self.debug = False
            Domoticz.Debugging(0)

        self.create_devices()
        Domoticz.Heartbeat(10)

    def onStop(self):
        Domoticz.Log("UPS-NUT Plugin stopped")
        Domoticz.Debugging(0)

    def onCommand(self, Unit, Command, Level, Color):
        Domoticz.Log(f"UPS-NUT: onCommand Unit={Unit} Command={Command} Level={Level}")

    def onHeartbeat(self):
        if self.debug:
            Domoticz.Debug("UPS-NUT: onHeartbeat called")

        self.counter += 1
        if self.counter < self.poll_interval:
            return

        self.counter = 0
        data = self.get_nut_data()
        if data:
            self.update_devices(data)

    def create_device(self, unit, name, dtype, subtype, switchtype=None, options=None, image=None):
        if unit in Devices:
            return

        kwargs = {
            "Unit": unit,
            "Name": name,
            "Type": dtype,
            "Subtype": subtype,
            "Used": 1
        }
        if switchtype is not None:
            kwargs["Switchtype"] = switchtype
        if options is not None:
            kwargs["Options"] = options
        if image is not None:
            kwargs["Image"] = image

        Domoticz.Device(**kwargs).Create()

    def create_devices(self):
        # 1 = status text
        self.create_device(1, "UPS Status", 243, 19)
        self.create_device(2, "Battery (%)", 243, 6)
        self.create_device(3, "UPS autonomy (min)", 243, 31)
        self.create_device(4, "Input Voltage", 243, 8)
        self.create_device(5, "Output Voltage", 243, 8)
        self.create_device(6, "UPS Load (%)", 243, 6)
        self.create_device(7, "UPS Info", 243, 19)
        self.create_device(8, "Power supply", 244, 73, switchtype=0)

    def get_nut_data(self):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((self.host, self.port))

            cmd = f"LIST VAR {self.ups_name}\n"
            s.sendall(cmd.encode("utf-8"))

            data = ""
            while True:
                chunk = s.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    break
                data += chunk
                if "END LIST VAR" in data:
                    break

            return self.parse_nut(data)

        except Exception as e:
            Domoticz.Error(f"UPS-NUT: NUT connection error: {e}")
            return None

        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass

    def parse_nut(self, raw):
        result = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("VAR "):
                continue

            parts = line.split(" ", 3)
            if len(parts) != 4:
                continue

            key = parts[2]
            value = parts[3].strip()

            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]

            result[key] = value

        return result

    def update_if_changed(self, unit, nvalue, svalue):
        if unit not in Devices:
            return
        if Devices[unit].nValue != nvalue or Devices[unit].sValue != str(svalue):
            Devices[unit].Update(nValue=nvalue, sValue=str(svalue))

    def update_devices(self, d):
        battery = d.get("battery.charge", "")
        runtime = d.get("battery.runtime", "")
        input_voltage = d.get("input.voltage", "")
        output_voltage = d.get("output.voltage", "")
        ups_load = d.get("ups.load", "")
        status = d.get("ups.status", "")
        model = d.get("ups.model", "")

        if battery != "":
            self.update_if_changed(2, 0, battery)

        if runtime != "":
            try:
                runtime_sec = int(float(runtime))
                runtime_min = int(runtime_sec / 60)
                self.update_if_changed(3, 0, runtime_min)
            except Exception:
                pass

        if input_voltage != "":
            self.update_if_changed(4, 0, input_voltage)

        if output_voltage != "":
            self.update_if_changed(5, 0, output_voltage)

        if ups_load != "":
            self.update_if_changed(6, 0, ups_load)

        # Status text + mains power switch
        if status:
            status_text = "Unknown"
            mains_power = 0  # Off = secteur absent

            if "OB" in status and "LB" in status:
                status_text = "On Battery - Low Battery"
                mains_power = 0
            elif "OB" in status:
                status_text = "On Battery"
                mains_power = 0
            elif "OL" in status:
                status_text = "On Line"
                mains_power = 1
            else:
                status_text = status

            try:
                if battery != "" and int(float(battery)) <= self.low_battery_threshold and "On Battery" in status_text:
                    status_text += f" ({battery}%)"
            except Exception:
                pass

            self.update_if_changed(1, 0, status_text)
            self.update_if_changed(8, mains_power, "On" if mains_power else "Off")

        info = f"{model} | In:{input_voltage}V | Batt:{battery}% | Load:{ups_load}%"
        self.update_if_changed(7, 0, info)


global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()
