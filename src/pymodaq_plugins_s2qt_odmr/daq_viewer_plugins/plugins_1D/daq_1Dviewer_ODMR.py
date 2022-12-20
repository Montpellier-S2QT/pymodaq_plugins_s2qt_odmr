import numpy as np
from easydict import EasyDict as edict
from pymodaq.utils.daq_utils import ThreadCommand, getLineInfo
from pymodaq.utils.data import DataFromPlugins, Axis
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, \
    comon_parameters, main
from pymodaq.utils.parameter import Parameter
from pymodaq.utils.parameter import utils as putils
from pymodaq_plugins_rohdeschwarz.hardware.SMA_SMB_MW_sources import MWsource
from pymodaq_plugins_daqmx.hardware.national_instruments.daqmx import DAQmx, \
    Edge, ClockSettings, Counter, TriggerSettings, AIChannel
from PyDAQmx import DAQmxConnectTerms, DAQmx_Val_DoNotInvertPolarity, \
    DAQmx_Val_ContSamps, DAQmx_Val_FiniteSamps, DAQmx_Val_CurrReadPos, \
    DAQmx_Val_DoNotOverwriteUnreadSamps, DAQmx_Val_Rising
# shared UnitRegistry from pint initialized in __init__.py
from pymodaq_plugins_s2qt_odmr import ureg, Q_

debug_add = "USB::0x0AAD::0x0054::105357::INSTR"

class DAQ_1DViewer_ODMR(DAQ_Viewer_base):
    """ Plugin generating a 1D viewer based on a RS MW source
    and a NI card based counter to perform ODMR measurement of
    fluorescent defects. This object inherits all functionality to
    communicate with PyMoDAQ Module through inheritance of
    DAQ_Viewer_base.
    """
    params = comon_parameters + [
        {"title": "Epsilon", "name": "epsilon", "type": "float",
         "value": 0.1, "visible": False},
         {"title": "MW source settings", "name": "mwsettings", "type":
          "group", "children": [
              {"title": "Address:", "name": "address", "type": "str",
               "value": debug_add},
              {"title": "Power (dBm):", "name": "power", "type": "float",
               "value": 0}
          ]},
         {"title": "Counter settings:", "name": "counter_settings",
          "type": "group", "visible": True, "children": [
              {"title": "Count time (ms):", "name": "counting_time",
                 "type": "float", "value": 100., "default": 100., "min": 0.},
              {"title": "Counting channel:", "name": "counter_channel",
               "type": "list",
               "limits": DAQmx.get_NIDAQ_channels(source_type="Counter")},
              {"title": "Source settings:", "name": "source_settings",
               "type": "group", "visible": True, "children": [
                   {"title": "Enable?:", "name": "enable", "type": "bool",
                    "value": False, },
                   {"title": "Photon source:", "name": "photon_channel",
                    "type": "list", "limits": DAQmx.getTriggeringSources()},
                   {"title": "Edge type:", "name": "edge", "type": "list",
                    "limits": Edge.names(), "visible": False},
                   {"title": "Level:", "name": "level", "type": "float",
                    "value": 1., "visible": False}
               ]}
          ]},
        {"title": "Acquisition settings", "name": "acq_settings", "type":
          "group", "children": [
              {"title": "Sweep mode?", "name": "sweep", "type": "bool",
               "value": True},
              {"title": "Number of ranges", "name": "nb_ranges",
               "type": "int", "value": 1, "min": 1},
              {"title": "Range parameters", "name": "range0", "type":
               "group", "children":[
                   {"title": "Start (MHz):", "name": "start", "type": "float",
                    "value": 2820},
                   {"title": "Stop (MHz):", "name": "stop", "type": "float",
                    "value": 2920},
                   {"title": "Step (MHz):", "name": "step", "type": "float",
                    "value": 2},
               ]},
              {"title": "List mode?", "name": "list", "type": "bool",
               "value": False}
          ]},
        {"title": "Further NI card settings", "name": "ni_settings", "type":
          "group", "children": [
              {'title': 'Clock channel:', 'name': 'clock_channel', 'type': 'list',
                  'limits': DAQmx.get_NIDAQ_channels(source_type='Counter')},
              {'title': 'Topo channel:', 'name': 'topo_channel', 'type': 'list',
                  'limits': DAQmx.get_NIDAQ_channels(source_type='Analog_Input')},
              {'title': 'Sync trigger channel:', 'name': 'sync_channel', 'type': 'list',
                'limits': DAQmx.getTriggeringSources()},
              ]}
        
    ]

    def ini_attributes(self):
        self.mw_controller = None
        self.counter_controller = None

        self.x_axis = None
        self.start = 2820 * ureg.MHz
        self.stop = 2920 * ureg.MHz
        self.step = 2 * ureg.MHz
        self.sweep_mode = False
        self.list_mode = False
        self.nb_ranges = 1
        self.live = False  # True during a continuous grab

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector
        settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value
            has been changed by the user
        """
        # MW settings
        if param.name() == "address":
            self.mw_controller.set_address(param.value())
        elif param.name() == "power":
            power_to_set = Q_(param.value(), ureg.dBm)
            self.mw_controller.set_cw_params(power=power_to_set)
        
        # Freq sweep settings
        if param.name() == "sweep":
            if param.value() and self.nb_ranges == 1:
                self.sweep_mode = True
                self.list_mode = False
                self.mw_controller.set_sweep()
                self.settings.child("list").setValue(False)
            else: # we consider the use of several ranges as sweep mode for the user,
                # but the controller needs to be used in list mode
                self.sweep_mode = False
                self.list_mode = True
                self.mw_controller.set_list()
                if param.value():
                    self.settings.child("list").setValue(False)

        elif param.name() == "list":
            if param.value():
                self.sweep_mode = False
                self.list_mode = True
                self.mw_controller.set_list()
                self.settings.child("sweep").setValue(False)
            elif self.nb_ranges==1:
                self.sweep_mode = True
                self.list_mode = False
                self.mw_controller.set_sweep()
                self.settings.child("sweep").setValue(True)
            else:
                self.sweep_mode = False
                self.list_mode = True
                self.mw_controller.set_list()
                self.settings.child("sweep").setValue(True)
                    
        elif param.name() == "nb_ranges":
            self.nb_ranges = param.value()
            self.update_x_axis()
        elif param.name() == "start":
            self.start = param.value() * ureg.MHz
            self.update_x_axis()
        elif param.name() == "stop":
            self.stop = param.value() * ureg.MHz
            self.update_x_axis()
        elif param.name() == "step":
            self.step = param.value() * ureg.MHz
            self.update_x_axis()

    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin. Do not use the ODMR
            in Slave configuration!!!
        
        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """
        self.mw_controller = MWsource()
        mw_initialized = self.mw_controller.open_communication(
            address=self.settings.child("mwsettings", "address").value())
        
        try:
            self.counter_controller = {"clock": DAQmx(), "counter": DAQmx(),
                                       "ai": DAQmx()}
            self.update_tasks()
            counter_initialized = True
        except Exception as e:
            print(e)
            counter_initialized = False

        initialized = mw_initialized and counter_initialized
        info = "Error"

        if initialized:
            info = f"MW source {self.mw_controller.model}"
            self.settings.child("mwsettings", "address").setValue(
                self.mw_controller.get_address())
            self.settings.child("mwsettings", "power").setValue(
                self.mw_controller.get_power().magnitude)
            self.update_x_axis()
            # Initialize viewers panel with the future type of data
            self.data_grabed_signal_temp.emit(
                [DataFromPlugins(name='ODMR', data=[np.zeros(len(self.x_axis['data']))],
                                 dim='Data1D', labels=['ODMR'],
                                 x_axis=self.x_axis),
                 DataFromPlugins(name='Topo', data=[np.array([0])],
                                 dim='Data0D', labels=['Topo'])])     
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        self.mw_controller.close_communication()
        self.counter_controller.close()
        
    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging, not relevant here.
        kwargs: dict
            others optionals arguments
        """
        update = False # to decide if we do the initial set up or not
        if self.sweep_mode:
            self.mw_controller.reset_sweep_position()
        else:
            self.mw_controller.reset_list_position()
        
        if 'live' in kwargs:
            if kwargs['live'] != self.live:
                update = True # we are not already live
            self.live = kwargs['live']

        odmr_length = len(self.x_axis["data"])
        
        if update:
            self.update_tasks()
            if self.sweep_mode:
                self.mw_controller.set_sweep(start=self.start, stop=self.stop,
                                             step=self.step,
                                             power=Q_(self.settings.child("power").value(),
                                                      ureg.dBm))
                self.mw_controller.sweep_on()
            else:
                self.emit_status(ThreadCommand('Update_Status',
                                               ['List mode not supported yet']))
                return

        # synchrone version (blocking function)
        # set timing for odmr clock task to the number of pixels
        self.counter_controller["clock"].task.CfgImplicitTiming(DAQmx_Val_FiniteSamps,
                                                                odmr_length+1)
        # set timing for odmr count task to the number of pixels
        self.counter_controller["counter"].task.CfgImplicitTiming(DAQmx_Val_ContSamps,
                # count twice for each voltage +1 for starting this task.
                # This first pulse will start the count task.
                                                                  2*(odmr_length+1))
        # read samples from beginning of acquisition, do not overwrite
        self.counter_controller["counter"].task.SetReadRelativeTo(DAQmx_Val_CurrReadPos)
        # do not read first sample
        self.counter_controller["counter"].task.SetReadOffset(0)
        # unread data in buffer will be overwritten
        self.counter_controller["counter"].task.SetReadOverWrite(DAQmx_Val_DoNotOverwriteUnreadSamps)
        # Topo analog input
        self.counter_controller["ai"].task.CfgSampClkTiming(self.clock_channel.name + "InternalOutput",
                                                            self.clock_channel.clock_frequency,
                                                            DAQmx_Val_Rising, DAQmx_Val_ContSamps,
                                                            odmr_length+1)
        try:
            self.counter_controller["counter"].start()
            self.counter_controller["ai"].start()
        except:
            self.emit_status(ThreadCommand('Update_Status',
                                               ['Cannot start ODMR counter']))
            
        try:
            timeout = 10
            self.counter_controller["clock"].start()
            self.counter_controller["clock"].task.WaitUntilTaskDone(timeout*2*odmr_length)
            
            
        
        acq_time = odmr_length * self.settings.child("counter_settings",
                                                     "counting_time").value()/1000
        data_pl = self.counter_controller.readCounter(odmr_length, counting_time=acq_time)
        data_topo = self.counter_controller.readAnalog(1, ClockSettings(
            frequency=self.clock_channel.clock_frequency,
            Nsamples=odmr_length))
        
        self.data_grabed_signal.emit([DataFromPlugins(name='ODMR', data=[data_pl],
                                                      dim='Data1D', labels=['PL'],
                                                      x_axis=self.x_axis),
                                      DataFromPlugins(name='Topo', data=[np.mean(data_topo)],
                                                      dim='Data0D', labels=["Topo"])])

    def stop(self):
        """Stop the current grab hardware wise if necessary."""
        self.counter_controller.close()
        self.mw_controller.mw_off()
        self.emit_status(ThreadCommand('Update_Status', ['Acquisition stopped']))
        return ''

    def update_x_axis(self):
        """Create the frequency list for the ODMR measurement."""
        if self.nb_ranges == 1:
            # we can use the sweep mode.
            freqs = np.arange(self.start.to(ureg.MHz).magnitude,
                              (self.stop + self.step).to(ureg.MHz).magnitude,
                              self.step.to(ureg.MHz).magnitude, dtype=np.float32)
            self.x_axis = Axis(data=freqs, label="Frequency", units="MHz")
        else:
            self.emit_status(ThreadCommand('Update_Status',
                                           ['Several ranges not supported yet']))

    def update_tasks(self):
        """Set up the counting tasks synchronized with the MW source
        in the NI card."""
        
        self.update_x_axis()

        # Create channels
        clock_freq = 1.0 / (self.settings.child("counter_settings", "counting_time").value()/1000)
        self.clock_channel = ClockCounter(self.settings.child("ni_settings",
                                                         "clock_channel").value(),
                                     source="Counter", clock_frequency=clock_freq)
        
        self.counter_channel = SemiPeriodCounter(name=self.settings.child("counter_settings",
                                                                "counter_channel").value(),
                                       source="Counter", value_max=5e6)
        
        self.topo_channel = AIChannel(name=self.settings.child("ni_settings",
                                                               "topo_channel").value(),
                                      source="Analog_Input")
        

        # configure tasks
        self.counter_controller["clock"].update_task(channels=[self.clock_channel],
                                                     # do not configure clock yet, so Nsamples=1
                                                     clock_settings=ClockSettings(Nsamples=1),
                                                     trigger_settings=TriggerSettings())
        self.counter_controller["counter"].update_task(channels=[self.counter_channel],
                                                       clock_settings=ClockSettings(Nsamples=1),
                                                       trigger_settings=TriggerSettings())
        self.counter_controller["ai"].update_task(channels=[self.topo_channel],
                                                       clock_settings=ClockSettings(Nsamples=1),
                                                       trigger_settings=TriggerSettings())

        # connect the pulses from the clock to the counter
        self.counter_controller["counter"].task.SetCICtrSemiPeriodTerm(
            self.counter_channel.name, self.clock_channel.name + "InternalOutput")
        # define the source of ticks for the counter as self._photon_source
        self.counter_controller["counter"].task.SetCICtrTimebaseSrc(
            self.counter_channel.name, self.settings.child("counter_settings",
                                                           "source_settings", "photon_channel").value())
        # connect the clock to the trigger channel to give triggers for the microwave
        DAQmxConnectTerms(self.clock_channel.name + "InternalOutput",
                          self.settings.child("ni_settings", "sync_channel").value(),
                          DAQmx_Val_DoNotInvertPolarity)

        
if __name__ == '__main__':
    main(__file__)

