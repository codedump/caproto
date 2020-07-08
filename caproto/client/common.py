# This is a channel access client implemented in a asyncio-agnostic way.

# It builds on the abstractions used in caproto, adding transport and some
# caches for matching requests with responses.
#
# VirtualCircuit: has a caproto.VirtualCircuit, a socket, and some caches.
# Channel: has a VirtualCircuit and a caproto.ClientChannel.
# Context: has a caproto.Broadcaster, a UDP socket, a cache of
#          search results and a cache of VirtualCircuits.
#
import os
import getpass

import caproto as ca


class ChannelReadError(Exception):
    ...

# TODO rely on these with the threading client

def _sentinel(name):
    class Sentinel:
        def __repr__(self):
            return name
    return Sentinel()

CIRCUIT_DEATH_ATTEMPTS = 3

# sentinels used as default values for arguments
GLOBAL_DEFAULT_TIMEOUT = os.environ.get("CAPROTO_DEFAULT_TIMEOUT", 2)

CONTEXT_DEFAULT_TIMEOUT = _sentinel('CONTEXT_DEFAULT_TIMEOUT')
PV_DEFAULT_TIMEOUT = _sentinel('PV_DEFAULT_TIMEOUT')
VALID_CHANNEL_MARKER = _sentinel('VALID_CHANNEL_MARKER')

AUTOMONITOR_MAXLENGTH = 65536
TIMEOUT = 2
EVENT_ADD_BATCH_MAX_BYTES = 2**16
MIN_RETRY_SEARCHES_INTERVAL = 0.03
MAX_RETRY_SEARCHES_INTERVAL = 5
SEARCH_RETIREMENT_AGE = 8 * 60
RETRY_RETIRED_SEARCHES_INTERVAL = 60
RESTART_SUBS_PERIOD = 0.1
STR_ENC = os.environ.get('CAPROTO_STRING_ENCODING', 'latin-1')


# class VirtualCircuit:
#     "Wraps a caproto.VirtualCircuit and adds transport."
#     def __init__(self, circuit):
#         self.circuit = circuit  # a caproto.VirtualCircuit
#         self.log = circuit.log
#         self.channels = {}  # map cid to Channel
#         self.ioids = {}  # map ioid to Channel
#         self.ioid_data = {}  # map ioid to server response
#         self.subscriptionids = {}  # map subscriptionid to Channel
#         self.connected = True
#         self.socket = None

#         # These must be provided by the implementation #
#         self.new_command_condition = None  # A Condition with awaitable
#         self._socket_lock = None  # A non-recursive lock

#     async def connect(self):
#         await self._connect()
#         # Send commands that initialize the Circuit.
#         await self.send(ca.VersionRequest(
#             version=ca.DEFAULT_PROTOCOL_VERSION,
#             priority=self.circuit.priority))
#         host_name = await self._get_host_name()
#         await self.send(ca.HostNameRequest(name=host_name))
#         client_name = getpass.getuser()
#         await self.send(ca.ClientNameRequest(name=client_name))

class ClientException(Exception):
    ...


class ChannelReadError(ClientException):
    ...


class DisconnectedError(ClientException):
    ...


class ContextDisconnectedError(ClientException):
    ...
