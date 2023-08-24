import numpy as np
from easydict import EasyDict as edict

from pymodaq.utils.daq_utils import ThreadCommand, getLineInfo
from pymodaq.utils.data import DataFromPlugins, Axis, DataToExport
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, \
    comon_parameters, main
from pymodaq.utils.parameter import Parameter
from pymodaq.utils.parameter import utils as putils

from pymodaq_plugins_rohdeschwarz.hardware.SMA_SMB_MW_sources import MWsource
from pymodaq_plugins_daqmx.hardware.national_instruments.daqmx import DAQmx, \
    Edge, ClockSettings, ClockCounter, SemiPeriodCounter, TriggerSettings, AIChannel
from PyDAQmx import DAQmxConnectTerms, DAQmx_Val_DoNotInvertPolarity, \
     DAQmx_Val_ContSamps, DAQmx_Val_FiniteSamps, DAQmx_Val_CurrReadPos, \
     DAQmx_Val_DoNotOverwriteUnreadSamps, DAQmx_Val_Rising

# shared UnitRegistry from pint initialized in __init__.py
from pymodaq_plugins_s2qt_odmr import ureg, Q_

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
              {"title": "Address:", "name": "address", "type": "str", "value": ''},
              {"title": "Power (dBm):", "name": "power", "type": "float", "value": 0}]},
         {"title": "Counter settings:", "name": "counter_settings",
          "type": "group", "visible": True, "children": [
              {"title": "Count time (ms):", "name": "counting_time",
                 "type": "float", "value": 100., "default": 100., "min": 0.},
              {"title": "Counting channel:", "name": "counter_channel", "type": "list",
               "limits": DAQmx.get_NIDAQ_channels(source_type="Counter")},
              {"title": "Source settings:", "name": "source_settings", "type": "group", "visible": True, "children": [
                   {"title": "Enable?:", "name": "enable", "type": "bool", "value": False, },
                   {"title": "Photon source:", "name": "photon_channel", "type": "list",
                    "limits": DAQmx.getTriggeringSources()},
                   {"title": "Edge type:", "name": "edge", "type": "list", "limits": Edge.names(), "visible": False},
                   {"title": "Level:", "name": "level", "type": "float", "value": 1., "visible": False}]}
         ]},
        {"title": "Acquisition settings", "name": "acq_settings", "type":
          "group", "children": [
              {"title": "Sweep mode?", "name": "sweep", "type": "bool", "value": True},
              {"title": "Number of ranges", "name": "nb_ranges", "type": "int", "value": 1, "min": 1},
              {"title": "Range parameters", "name": "range0", "type":
               "group", "children":[
                   {"title": "Start (MHz):", "name": "start_f", "type": "float", "value": 2820},
                   {"title": "Stop (MHz):", "name": "stop_f", "type": "float", "value": 2920},
                   {"title": "Step (MHz):", "name": "step_f", "type": "float", "value": 2},
               ]},
              {"title": "List mode?", "name": "list", "type": "bool", "value": False}]},
        {"title": "Further NI card settings", "name": "ni_settings", "type":
          "group", "children": [
              {'title': 'Clock channel:', 'name': 'clock_channel', 'type': 'list',
                  'limits': DAQmx.get_NIDAQ_channels(source_type='Counter')},
              {'title': 'Topo channel:', 'name': 'topo_channel', 'type': 'list',
                  'limits': DAQmx.get_NIDAQ_channels(source_type='Analog_Input')},
              {'title': 'Sync trigger channel:', 'name': 'sync_channel', 'type': 'list',
                'limits': DAQmx.getTriggeringSources()},]}
    ]

    def ini_attributes(self):
        self.controller = None

        self.x_axis = None
        self.start_f = 2820 * ureg.MHz
        self.stop_f = 2920 * ureg.MHz
        self.step_f = 2 * ureg.MHz
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
            self.controller["mw"].set_address(param.value())
        elif param.name() == "power":
            power_to_set = Q_(param.value(), ureg.dBm)
            self.controller["mw"].set_cw_params(power=power_to_set)
        
        # Freq sweep settings
        if param.name() == "sweep":
            if param.value() and self.nb_ranges == 1:
                self.sweep_mode = True
                self.list_mode = False
                self.controller["mw"].set_sweep()
                self.settings.child("acq_settings", "list").setValue(False)
            else:  # we consider the use of several ranges as sweep mode for the user,
                # but the controller needs to be used in list mode
                self.sweep_mode = False
                self.list_mode = True
                self.controller["mw"].set_list()
                if param.value():
                    self.settings.child("acq_settings", "list").setValue(False)

        elif param.name() == "list":
            if param.value():
                self.sweep_mode = False
                self.list_mode = True
                self.controller["mw"].set_list()
                self.settings.child("acq_settings", "sweep").setValue(False)
            elif self.nb_ranges == 1:
                self.sweep_mode = True
                self.list_mode = False
                self.controller["mw"].set_sweep()
                self.settings.child("acq_settings", "sweep").setValue(True)
            else:
                self.sweep_mode = False
                self.list_mode = True
                self.controller["mw"].set_list()
                self.settings.child("acq_settings", "sweep").setValue(True)
                    
        elif param.name() == "nb_ranges":
            self.nb_ranges = param.value()
            self.update_x_axis()
        elif param.name() == "start_f":
            self.start_f = param.value() * ureg.MHz
            self.update_x_axis()
        elif param.name() == "stop_f":
            self.stop_f = param.value() * ureg.MHz
            self.update_x_axis()
        elif param.name() == "step_f":
            self.step_f = param.value() * ureg.MHz
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
        self.controller = {"mw": MWsource(),
                           "counter": {"clock": DAQmx(), "counter": DAQmx(), "ai": DAQmx()}}
        mw_initialized = self.controller["mw"].open_communication(
                               address=self.settings.child("mwsettings", "address").value())
        try:
            self.update_tasks()
            counter_initialized = True
        except Exception as e:
            print(e)
            counter_initialized = False

        initialized = mw_initialized and counter_initialized
        info = "Error"

        if initialized:
            info = f"MW source {self.controller['mw'].model}"
            self.settings.child("mwsettings", "address").setValue(
                self.controller["mw"].get_address())
            self.settings.child("mwsettings", "power").setValue(
                self.controller["mw"].get_power().magnitude)
            self.update_x_axis()
            # Initialize viewers panel with the future type of data
            self.dte_signal_temp.emit(DataToExport(name='temp_odmr',
                 data=[DataFromPlugins(name='ODMR', data=[np.zeros(self.x_axis.size)],
                                       dim='Data1D', labels=['ODMR'],
                                       axes=[self.x_axis]),
                       DataFromPlugins(name='Topo', data=[np.array([0])],
                                       dim='Data0D', labels=['Topo'])]))
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        self.controller["mw"].close_communication()
        self.controller["counter"]["clock"].close()
        self.controller["counter"]["counter"].close()
        self.controller["counter"]["ai"].close()
        
    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging, not relevant here.
        kwargs: dict
            others optionals arguments
        """
        update = True  # to decide if we do the initial set up or not
        self.commit_settings(self.settings.child("acq_settings", "sweep"))
        if self.sweep_mode:
            self.controller["mw"].reset_sweep_position()
        else:
            self.controller["mw"].reset_list_position()
        
        if 'live' in kwargs:
            if kwargs['live'] == self.live and self.live:
                update = False  # we are already live
            self.live = kwargs['live']

        odmr_length = self.x_axis.size

        if not update:
             self.configure_tasks()
             self.connect_channels()
             self.controller["mw"].sweep_on()
        else:
            self.update_tasks()
            if self.sweep_mode:
                self.controller["mw"].set_sweep(start=self.start_f, stop=self.stop_f,
                                             step=self.step_f,
                                             power=Q_(self.settings.child("mwsettings", "power").value(),
                                                      ureg.dBm))
                self.controller["mw"].sweep_on()
            else:
                self.emit_status(ThreadCommand('Update_Status',
                                               ['List mode not supported yet']))
                return

        # synchrone version (blocking function)
        # set timing for odmr clock task to the number of pixels
        self.controller["counter"]["clock"].stop()  # to ensure that the clock is available
        self.controller["counter"]["clock"].task.CfgImplicitTiming(DAQmx_Val_FiniteSamps,
                                                                odmr_length+1)
        # set timing for odmr count task to the number of pixels
        self.controller["counter"]["counter"].task.CfgImplicitTiming(DAQmx_Val_ContSamps,
                # count twice for each voltage +1 for starting this task.
                # This first pulse will start the count task.
                                                                  2*(odmr_length+1))
        # read samples from beginning of acquisition, do not overwrite
        self.controller["counter"]["counter"].task.SetReadRelativeTo(DAQmx_Val_CurrReadPos)
        # do not read first sample
        self.controller["counter"]["counter"].task.SetReadOffset(0)
        # unread data in buffer will be overwritten
        self.controller["counter"]["counter"].task.SetReadOverWrite(DAQmx_Val_DoNotOverwriteUnreadSamps)
        # Topo analog input
        self.controller["counter"]["ai"].task.CfgSampClkTiming('/' + self.clock_channel.name + "InternalOutput",
                                                            self.clock_channel.clock_frequency,
                                                            DAQmx_Val_Rising, DAQmx_Val_ContSamps,
                                                            odmr_length+1)
        try:
            self.controller["counter"]["ai"].start()
            self.controller["counter"]["counter"].start()
        except Exception as e:
            print(e)
            self.emit_status(ThreadCommand('Update_Status',
                                               ['Cannot start ODMR counter']))
            return

        try:
            timeout = 10
            self.controller["counter"]["clock"].start()
            self.controller["counter"]["clock"].task.WaitUntilTaskDone(timeout*2*odmr_length)
        except Exception as e:
            print(e)
            self.emit_status(ThreadCommand('Update_Status',
                                               ['Cannot start ODMR clock']))
            return

        time_per_point = self.settings.child("counter_settings",
                                                     "counting_time").value()/1000
        acq_time = odmr_length * time_per_point
     
        
        read_data = self.controller["counter"]["counter"].readCounter(2*odmr_length+1,
                                                    counting_time=acq_time, read_function="")
        # add up adjoint pixels to also get the counts from the low time of the clock
        data_pl = read_data[:-1:2]
        data_pl += read_data[1:-1:2]
        # we need to divide by the measurement time to get the PL rate!
        data_pl = 1e-3*data_pl/time_per_point # we show kcts/s
        
        data_topo = self.controller["counter"]["ai"].readAnalog(1, ClockSettings(
            frequency=self.clock_channel.clock_frequency,
            Nsamples=odmr_length))
        
        self.dte_signal.emit(DataToExport(name='odmr',
                                                  data=[DataFromPlugins(name='ODMR', data=[data_pl],
                                                        dim='Data1D', labels=['PL (kcts/s)'],
                                                        axes=[self.x_axis]),
                                                        DataFromPlugins(name='Topo',
                                                                data=[np.array([np.mean(data_topo)])],
                                                                dim='Data0D', labels=["Topo (nm)"])]))

    def stop(self):
        """Stop the current grab hardware wise if necessary."""
        for daq_str in self.controller["counter"].keys():
            self.controller["counter"][daq_str].close()
        self.controller["mw"].off()
        self.emit_status(ThreadCommand('Update_Status', ['Acquisition stopped']))
        return ''

    def update_x_axis(self):
        """Create the frequency list for the ODMR measurement."""
        if self.nb_ranges == 1:
            # we can use the sweep mode.
            freqs = np.arange(self.start_f.to(ureg.MHz).magnitude,
                              (self.stop_f + self.step_f).to(ureg.MHz).magnitude,
                              self.step_f.to(ureg.MHz).magnitude, dtype=np.float32)
            self.x_axis = Axis(label="Frequency", units="MHz", data=freqs)
        else:
            self.emit_status(ThreadCommand('Update_Status',
                                           ['Several ranges not supported yet']))

    def update_tasks(self):
        """Set up the counting tasks synchronized with the MW source
        in the NI card."""
        
        self.update_x_axis()

        # Create channels
        self.create_channels()
        # configure tasks
        self.configure_tasks()
        # connect everything
        self.connect_channels()

    def create_channels(self):
        """ Create the channels in the NI card to update the tasks."""
        clock_freq = 1.0 / (self.settings.child("counter_settings", "counting_time").value()/1000)
        self.clock_channel = ClockCounter(clock_freq, name=self.settings.child("ni_settings",
                                          "clock_channel").value(), source="Counter")
        
        self.counter_channel = SemiPeriodCounter(5e6, name=self.settings.child("counter_settings",
                                                 "counter_channel").value(), source="Counter")
        #self.counter_channel.name = '/'+self.counter_channel.name
        
        self.topo_channel = AIChannel(name=self.settings.child("ni_settings",
                                      "topo_channel").value(), source="Analog_Input")

    def configure_tasks(self):
        """ Configure the tasks in the NI card, by calling the update functions of each controller."""
        self.controller["counter"]["clock"].update_task(channels=[self.clock_channel],
                                                        # do not configure clock yet, so Nsamples=1
                                                        clock_settings=ClockSettings(Nsamples=1),
                                                        trigger_settings=TriggerSettings())
        self.controller["counter"]["counter"].update_task(channels=[self.counter_channel],
                                                          clock_settings=ClockSettings(Nsamples=1),
                                                          trigger_settings=TriggerSettings())
        self.controller["counter"]["ai"].update_task(channels=[self.topo_channel],
                                                     clock_settings=ClockSettings(Nsamples=1),
                                                     trigger_settings=TriggerSettings())

    def connect_channels(self):
        """ Connect together the channels for synchronization."""
        # connect the pulses from the clock to the counter
        self.controller["counter"]["counter"].task.SetCISemiPeriodTerm(
            self.counter_channel.name, '/'+self.clock_channel.name + "InternalOutput")
        # define the source of ticks for the counter as self._photon_source
        self.controller["counter"]["counter"].task.SetCICtrTimebaseSrc(
            self.counter_channel.name, self.settings.child("counter_settings",
                                                           "source_settings", "photon_channel").value())
        # connect the clock to the trigger channel to give triggers for the microwave
        DAQmxConnectTerms("/" + self.clock_channel.name + "InternalOutput",
                          self.settings.child("ni_settings", "sync_channel").value(),
                          DAQmx_Val_DoNotInvertPolarity)
        
        
if __name__ == '__main__':
    main(__file__)

