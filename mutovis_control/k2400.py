import sys
import numpy as np
import time
from collections import deque
import visa
import warnings
import os

class k2400:
  """
  Intertace for Keithley 2400 sourcemeter
  """
  idnContains = 'KEITHLEY'
  quiet=False
  idn = ''

  def __init__(self, visa_lib='@py', scan=False, addressString=None, terminator='\n', serialBaud=57600, front=False, twoWire=False, quiet=False):
    self.quiet = quiet
    self.readyForAction = False
    self.rm = self._getResourceManager(visa_lib)

    if scan:
      print(self.rm.list_resources())

    self.addressString = addressString
    self.terminator = terminator
    self.serialBaud = serialBaud     
    self.sm = self._getSourceMeter(self.rm)
    self._setupSourcemeter(front=front, twoWire=twoWire)

  def __del__(self):
    try:
      pass
      g = self.sm.visalib.sessions[self.sm.session]
      g.close(g.interface.id)
      #self.sm.close()
    except:
      pass

  def _getResourceManager(self,visa_lib):
    try:
      rm = visa.ResourceManager(visa_lib)
    except:
      exctype, value1 = sys.exc_info()[:2]
      try:
        rm = visa.ResourceManager()
      except:
        exctype, value2 = sys.exc_info()[:2]
        print('Unable to connect to instrument.')
        print('Error 1 (using {:s} backend):'.format(visa_lib))
        print(value1)
        print('Error 2 (using pyvisa default backend):')
        print(value2)
        raise ValueError("Unable to create a resource manager.")

    vLibPath = rm.visalib.get_library_paths()[0]
    if vLibPath == 'unset':
      self.backend = 'pyvisa-py'
    else:
      self.backend = vLibPath
    
    if not self.quiet:
      print("Using {:s} pyvisa backend.".format(self.backend))
    return rm

  def _getSourceMeter(self, rm):
    timeoutMS = 300 # initial comms timeout
    if 'ASRL' in self.addressString:
      openParams = {'resource_name': self.addressString, 'timeout': timeoutMS, 'read_termination': self.terminator,'write_termination': self.terminator, 'baud_rate': self.serialBaud, 'flow_control':visa.constants.VI_ASRL_FLOW_XON_XOFF}
      smCommsMsg = "ERROR: Can't talk to sourcemeter\nDefault sourcemeter serial comms params are: 57600-8-n with <LF> terminator and xon-xoff flow control."
    elif 'GPIB' in self.addressString:
      openParams = {'resource_name': self.addressString, 'write_termination': self.terminator}# , 'io_protocol': visa.constants.VI_HS488
      addrParts = self.addressString.split('::')
      board = addrParts[0][4:]
      address = addrParts[1]
      smCommsMsg = "ERROR: Can't talk to sourcemeter\nIs GPIB controller {:} correct?\nIs the sourcemeter configured to listen on address {:}?".format(board,address)
    else:
      smCommsMsg = "ERROR: Can't talk to sourcemeter"
      openParams = {'resource_name': self.addressString}

    sm = rm.open_resource(**openParams)

    if sm.interface_type == visa.constants.InterfaceType.gpib:
      if os.name != 'nt':
        sm.send_ifc()
      sm.clear()
      sm._read_termination = '\n'

    try:
      sm.write('*RST')
      sm.write(':status:preset')
      sm.write(':system:preset')
      # ask the device to identify its self
      self.idn = sm.query('*IDN?')
    except:
      print('Unable perform "*IDN?" query.')
      exctype, value = sys.exc_info()[:2]
      print(value)
      #try:
      #  sm.close()
      #except:
      #  pass
      print(smCommsMsg)
      raise ValueError("Failed to talk to sourcemeter.")

    if self.idnContains in self.idn:
      if not self.quiet:
        print("Sourcemeter found:")
        print(self.idn)
    else:
      raise ValueError("Got a bad response to *IDN?: {:s}".format(self.idn))

    return sm

  def _setupSourcemeter(self, twoWire, front):
    """ Do initial setup for sourcemeter
    """
    sm = self.sm
    sm.timeout = 50000 #long enough to collect an entire sweep [ms]

    sm.write(':status:preset')
    sm.write(':system:preset')
    sm.write(':trace:clear')
    sm.write(':output:smode himpedance')
    
    warnings.filterwarnings("ignore")
    if sm.interface_type == visa.constants.InterfaceType.asrl:
      self.dataFormat = 'ascii'
      sm.values_format.use_ascii('f',',')
    elif sm.interface_type == visa.constants.InterfaceType.gpib:
      self.dataFormat = 'sreal'
      sm.values_format.use_binary('f', False, container=np.array)
    else:
      self.dataFormat = 'ascii'
      sm.values_format.use_ascii('f',',')
    warnings.resetwarnings()

    sm.write("format:data {:s}".format(self.dataFormat))

    sm.write('source:clear:auto off')


    self.setWires(twoWire=twoWire)

    sm.write(':sense:function:concurrent on')
    sm.write(':sense:function "current:dc", "voltage:dc"')
    sm.write(':format:elements time,voltage,current,status')

    # use front terminals?
    self.setTerminals(front=front)

    self.src = sm.query(':source:function:mode?')
    sm.write(':system:beeper:state off')
    sm.write(':system:lfrequency:auto on')
    sm.write(':system:time:reset')

    sm.write(':system:azero off')  # we'll do this once before every measurement
    sm.write(':system:azero:caching on')

    # TODO: look into contact checking function of 2400 :system:ccheck

  def setWires(self, twoWire=False):
    if twoWire:
      self.sm.write(':system:rsense off') # four wire mode off
    else:
      self.sm.write(':system:rsense on') # four wire mode on

  def setTerminals(self, front=False):
    if front:
      self.sm.write(':rout:term front')
    else:
      self.sm.write(':rout:term rear')

  def updateSweepStart(self,startVal):
    self.sm.write(':source:{:s}:start {:.8f}'.format(self.src, startVal))

  def updateSweepStop(self,stopVal):
    self.sm.write(':source:{:s}:stop {:.8f}'.format(self.src, stopVal))

  def setOutput(self, outVal):
    self.sm.write(':source:{:s} {:.8f}'.format(self.src,outVal))

  def write(self, toWrite):
    self.sm.write(toWrite)

  def query_values(self, query):
    if self.dataFormat == 'ascii':
      return self.sm.query_ascii_values(query)
    elif self.dataFormat == 'sreal':
      return self.sm.query_binary_values(query)
    else:
      raise ValueError("Don't know what values format to use!")

  def outOn(self, on=True):
    if on:
      self.sm.write(':output on')
    else:
      self.sm.write(':output off')

  def setNPLC(self,nplc):
    self.sm.write(':sense:current:nplcycles {:}'.format(nplc))
    self.sm.write(':sense:voltage:nplcycles {:}'.format(nplc))
    if nplc < 1:
      self.sm.write(':display:digits 5')
    else:
      self.sm.write(':display:digits 7')

  def setupDC(self, sourceVoltage=True, compliance=0.04, setPoint=0, senseRange='f'):
    """setup DC measurement operation
    if senseRange == 'a' the instrument will auto range for both current and voltage measurements
    if senseRange == 'f' then the sense range will follow the compliance setting
    if sourceVoltage == False, we'll have a current source at setPoint amps with max voltage +/- compliance volts
    """
    sm = self.sm
    if sourceVoltage:
      src = 'voltage'
      snc = 'current'
    else:
      src = 'current'
      snc = 'voltage'
    self.src = src
    sm.write(':source:function {:s}'.format(src))
    sm.write(':source:{:s}:mode fixed'.format(src))
    sm.write(':source:{:s} {:.8f}'.format(src,setPoint))

    sm.write(':source:delay:auto on')

    sm.write(':sense:{:s}:protection {:.8f}'.format(snc,compliance))

    if senseRange == 'f':
      sm.write(':sense:{:s}:range:auto off'.format(snc))
      sm.write(':sense:{:s}:protection:rsynchronize on'.format(snc))
    elif senseRange == 'a':
      sm.write(':sense:{:s}:range:auto on'.format(snc))
    else:
      sm.write(':sense:{:s}:range {:.8f}'.format(snc,senseRange))

    # this again is to make sure the sense range gets updated
    sm.write(':sense:{:s}:protection {:.8f}'.format(snc,compliance))

    sm.write(':output on')
    sm.write(':trigger:count 1')

    sm.write(':system:azero once')

  def setupSweep(self, sourceVoltage=True, compliance=0.04, nPoints=101, stepDelay=0.005, start=0, end=1, streaming=False, senseRange='f'):
    """setup for a sweep operation
    if senseRange == 'a' the instrument will auto range for both current and voltage measurements
    if senseRange == 'f' then the sense range will follow the compliance setting
    if stepDelay == -1 then step delay is on auto (1ms)
    """
    sm = self.sm
    if sourceVoltage:
      src = 'voltage'
      snc = 'current'
    else:
      src = 'current'
      snc = 'voltage'
    self.src = src
    sm.write(':source:function {:s}'.format(src))
    sm.write(':source:{:s} {:0.6f}'.format(src,start))

    # seems to do exactly nothing
    #if snc == 'current':
    #  holdoff_delay = 0.005
    #  sm.write(':sense:current:range:holdoff on')
    #  sm.write(':sense:current:range:holdoff {:.6f}'.format(holdoff_delay))
    #  self.opc()  # needed to prevent input buffer overrun with serial comms (should be taken care of by flowcontrol!)

    sm.write(':sense:{:s}:protection {:.8f}'.format(snc,compliance))

    if senseRange == 'f':
      sm.write(':sense:{:s}:range:auto off'.format(snc))
      sm.write(':sense:{:s}:protection:rsynchronize on'.format(snc))
    elif senseRange == 'a':
      sm.write(':sense:{:s}:range:auto on'.format(snc))
    else:
      sm.write(':sense:{:s}:range {:.8f}'.format(snc,senseRange))

    # this again is to make sure the sense range gets updated
    sm.write(':sense:{:s}:protection {:.8f}'.format(snc,compliance))

    sm.write(':output on')
    sm.write(':source:{:s}:mode sweep'.format(src))
    sm.write(':source:sweep:spacing linear')
    if stepDelay == -1:
      sm.write(':source:delay:auto on') # this just sets delay to 1ms
    else:
      sm.write(':source:delay:auto off')
      sm.write(':source:delay {:0.6f}'.format(stepDelay))
    sm.write(':trigger:count {:d}'.format(nPoints))
    sm.write(':source:sweep:points {:d}'.format(nPoints))
    sm.write(':source:{:s}:start {:.6f}'.format(src,start))
    sm.write(':source:{:s}:stop {:.6f}'.format(src,end))
    if sourceVoltage:
      self.dV = abs(float(sm.query(':source:voltage:step?')))
    else:
      self.dI = abs(float(sm.query(':source:current:step?')))
    #sm.write(':source:{:s}:range {:.4f}'.format(src,max(start,end)))
    sm.write(':source:sweep:ranging best')
    #sm.write(':sense:{:s}:range:auto off'.format(snc))

    sm.write(':system:azero once')

  def opc(self):
    """returns when all operations are complete
    """
    opcVAl = self.sm.query('*OPC?')
    return

  def arm(self):
    """arms trigger
    """
    self.sm.write(':init')

  def trigger(self):
    """permorms trigger event
    """
    if self.sm.interface_type == visa.constants.InterfaceType.gpib:
      self.sm.assert_trigger()
    else:
      self.sm.write('*TRG')

  def sendBusCommand(self, command):
    """sends a command over the GPIB bus
    See: https://linux-gpib.sourceforge.io/doc_html/gpib-protocol.html#REFERENCE-COMMAND-BYTES
    """
    if self.sm.interface_type == visa.constants.InterfaceType.gpib:
      self.sm.send_command(command)
      #self.sm.send_command(0x08) # whole bus trigger
    else:
      print('Bus commands can only be sent over GPIB')

  def measure(self):
    """Makes a measurement and returns the result
    """
    if self.sm.interface_type == visa.constants.InterfaceType.gpib:
      vals = self.sm.read_binary_values()
    else:
      vals = self.sm.query_ascii_values(':read?')
    return vals

  def measureUntil(self, t_dwell=np.inf, measurements=np.inf, cb=lambda x:None):
    """Meakes measurements until termination conditions are met
    supports a callback after every measurement
    returns a deque of measurements
    """
    i = 0
    t_end = time.time() + t_dwell
    q = deque()
    while (i < measurements) and (time.time() < t_end):
      i = i + 1
      measurement = self.measure()
      q.append(measurement)
      cb(measurement)
    return q
