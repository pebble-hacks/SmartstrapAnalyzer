import argparse
import serial
from array import array
from struct import *
import hdlc
import pyftdi.serialext


def crc8_calculate(data):
    LOOKUP_TABLE = [0, 47, 94, 113, 188, 147, 226, 205, 87, 120, 9, 38, 235, 196, 181, 154]
    crc = 0
    for x in range(0, len(data) * 2):
        nibble = data[x / 2]
        if x % 2 == 0:
            nibble = nibble >> 4
        index = nibble ^ (crc >> 4)
        crc = LOOKUP_TABLE[index & 0xf] ^ ((crc << 4) & 0xf0)
    return crc

Profile_LinkControl = 1
Profile_RawData = 2
Profile_GenericServivce = 3
LinkControlType_Status = 1
LinkControlType_Profiles = 2
LinkControlType_BaudRate = 3
LinkControlStatus_Ok = 0
LinkControlStatus_BaudRate = 1
LinkControlStatus_Disconnect = 2
GenericServiceType_Read = 0
GenericServiceType_Write = 1
GenericServiceType_WriteRead = 2
GenericServiceErrorCode_Ok = 0
GenericServiceErrorCode_NotSupported = 1

class Frame:
    FRAME_VERSION = 1


    class LinkControlPayload:
        PROFILE_VERSION = 1

        def __init__(self, raw_data):
            data = array('B', raw_data).tostring()
            self.version, self.msg_type = unpack('<BB', "".join(data[:2]))
            self.data = data[2:]

        def get_response_payload(self):
            data = pack("<BB", self.PROFILE_VERSION, self.msg_type)
            if self.msg_type == LinkControlType_Status:
                data += chr(LinkControlStatus_Ok)
            elif self.msg_type == LinkControlType_Profiles:
                data += pack("<HH", 0x02, 0x03)
            return data

        def __str__(self):
            if self.msg_type == LinkControlType_Status:
                return "Link Control | Status"
            elif self.msg_type == LinkControlType_Profiles:
                return "Link Control | Profiles"
            elif self.msg_type == LinkControlType_BaudRate:
                return "Link Control | BaudRate"
            else:
                return "Link Control | Unknown"


    class RawDataPayload:
        def __init__(self, data):
            self.data = data

        def get_response_payload(self):
            return ""

        def __str__(self):
            return "Raw Data"


    class GenericServicePayload:
        PROFILE_VERSION = 1

        def __init__(self, raw_data):
            data = array('B', raw_data).tostring()
            self.version, self.service_id, self.attribute_id, self.msg_type, self.error_code, self.length = unpack('<BHHBBH', "".join(data[:9]))
            self.data = data[9:]

        def get_response_payload(self):
            data = pack("<BHHB", self.PROFILE_VERSION, self.service_id, self.attribute_id, self.msg_type)
            if self.service_id == 0x0101:
                # management service
                if self.attribute_id == 0x0001:
                    # service discovery attribute
                    data += pack("<BHH", 0, 2, 0x1001)
                elif self.attribute_id == 0x0002:
                    # notification info attribute
                    data += pack("<BHHH", 0, 4, 0x1001, 0x0002);
            elif self.service_id == 0x1001:
                # custom service
                if self.attribute_id == 0x0001:
                    # led attribute
                    if ord(self.data[0]) != 0:
                        print("SET LED ON")
                    else:
                        print("SET LED OFF")
                    data += pack("<BH", 0, 0)
                elif self.attribute_id == 0x0002:
                    # uptime attribute
                    data += pack("<BHI", 0, 4, 1337)
            else:
                pass
            return data

        def __str__(self):
            if self.msg_type == 0:
                msg_type_str = "Read"
            elif self.msg_type == 1:
                msg_type_str = "Write"
            elif self.msg_type == 2:
                msg_type_str = "WriteRead"
            else:
                return "Generic Service | Invalid"
            data = "[" + ",".join([hex(n) for n in array('B', self.data)]) + "]"
            return "Generic Service | v%d | 0x%x, 0x%x | %s | %d bytes | %s" % (self.version, self.service_id, self.attribute_id, msg_type_str, self.length, data)


    class Flags:
        def __init__(self, data):
            self.read = bool(data[0] & (1 << 0))
            self.master = bool(data[0] & (1 << 1))
            self.notification = bool(data[0] & (1 << 2))


    def __init__(self, s):
        self.s = s

    def set_data(self, data):
        if len(data) < 8:
            return False
        if crc8_calculate(data) != 0:
            print("ERROR: Got frame with invalid checksum!")
            return False
        self.version = data[0]
        self.profile = data[5]
        self.flags = Frame.Flags(data[1:5])
        if self.flags.notification and self.flags.master:
            print("ERROR: Got notification frame from master!")
            return False
        if self.profile == Profile_LinkControl:
            self.payload = self.LinkControlPayload(data[7:-1])
        elif self.profile == Profile_RawData:
            self.payload = self.RawDataPayload(data[7:-1])
        elif self.profile == Profile_GenericServivce:
            self.payload = self.GenericServicePayload(data[7:-1])
        else:
            print("ERROR: Got frame for unsupported profile!")
            return False
        return True

    def __str__(self):
        lines = []
        if self.flags.master:
            if self.flags.read:
                lines.append("Watch Read | v%d" % self.version)
            else:
                lines.append("Watch Write | v%d" % self.version)
        else:
            if self.flags.notification:
                lines.append("Smartstrap Notification | v%d" % self.version)
            else:
                lines.append("Smartstrap Response | v%d" % self.version)
        lines.append("\t" + str(self.payload))
        return "\n".join(lines)


def open_serial_port(tty, baud_rate):
    s = serial.serial_for_url(tty, baudrate=baud_rate, timeout=0.001)
    s.open()
    s.udev.set_event_char(0x7E, True)
    if not s:
        raise Exception("Failed to open tty!")
    return s

import time
def decode_frames(s):
    context = hdlc.get_context();
    while True:
        result = hdlc.decode_data_streaming(context, s);
        if result:
            context = hdlc.get_context()
            frame = Frame(s)
            if frame.set_data(array("B", result)):
                print(str(frame) + "\n")
            else:
                print("Invalid frame of length %d" % len(result))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('serial_port', type=str,
                        help="Serial port (e.g. /dev/cu.usbserial-xxxxxxxB or /dev/ttyUSB0).")
    args = parser.parse_args()
    #tty_accessory = "ftdi://ftdi:4232:1/4"
    #tty_accessory = "ftdi://ftdi:230x:DA010MPD/2"
    s = open_serial_port(args.serial_port, 57600)
    decode_frames(s)
