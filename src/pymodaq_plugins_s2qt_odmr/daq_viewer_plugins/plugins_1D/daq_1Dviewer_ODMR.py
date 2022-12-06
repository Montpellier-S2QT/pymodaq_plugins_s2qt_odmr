import numpy as np
from easydict import EasyDict as edict
from pymodaq.utils.daq_utils import ThreadCommand, getLineInfo
from pymodaq.utils.data import DataFromPlugins, Axis
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, \
    comon_parameters, main
from pymodaq.utils.parameter import Parameter
from pymodaq.daq_utils.parameter import utils as putils
from pymodaq_plugins_rohdeschwarz.daq_move_plugins.daq_move_RSMWsource import \
    DAQ_Move_RSMWsource
from pymodaq_plugins_daqmx.daq_viewer_plugins.plugins_0D.daq_0Dviewer_DAQmx \
import DAQ_0DViewer_DAQmx
from pymodaq_plugins_daqmx.hardware.national_instruments.daqmx import DAQmx, \
    Edge
# shared UnitRegistry from pint initialized in __init__.py
from pymodaq_plugins_s2qt_odmr import ureg, Q_


class DAQ_1DViewer_ODMR(DAQ_0DViewer_DAQmx, DAQ_Move_RSMWsource):
    """ Plugin generating a hybrid 1D viewer based on a RS MW source
    and a NI card based counter to perform ODMR measurement of
    fluorescent defects. This object inherits all functionality to
    communicate with PyMoDAQ Module, MW source and NI card through
    inheritance of DAQ_0DViewer_DAQmx and DAQ_Move_RSMWsource.
    """
    params = comon_parameters + [
         {"title": "MW source settings", "name": "mwsettings", "type":
          "group", "children": [
              {"title": "Address:", "name": "address", "type": "str",
               "value": ""},
              {"title": "Power (dBm):", "name": "power", "type": "float",
               "value": 0}
          ]},
         {"title": "Counter Settings:", "name": "counter_settings",
          "type": "group", "visible": True, "children": [
              {"title": "Count time (ms):", "name": "counting_time",
                 "type": "float", "value": 100., "default": 100., "min": 0.},
              {"title": "Counting Channels:", "name": "counter_channels",
               "type": "groupcounter",
               "limits": DAQmx.get_NIDAQ_channels(source_type="Counter")},
              {"title": "Trigger Settings:", "name": "trigger_settings",
               "type": "group", "visible": True, "children": [
                   {"title": "Enable?:", "name": "enable", "type": "bool",
                    "value": False, },
                   {"title": "Trigger Source:", "name": "trigger_channel",
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
          ]}
    ]

    def __init__(self, parent=None, params_state=None):
        DAQ_0DViewer_DAQmx.__init__(self, parent, params_state)
        DAQ_Move_RSMWsource.__init__(self, parent, params_state)
        

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
        DAQ_Move_RSMWsource.commit_settings(self, param)
        # Counter settings
        DAQ_0DViewer_DAQmx.commit_settings(self, param)
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
            custom object of a PyMoDAQ plugin (Slave case). None if only
            one actuator/detector by controller
            (Master case)
        MIGHT BE AN ISSUE !!!
        
        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """
        status_mw = DAQ_Move_RSMWsource.ini_stage(self, controller)
        status_counter = DAQ_0DViewer_DAQmx.ini_detector(self, controller)

        initialized = status_mw[1] and status_counter.initialized
        info = f"MW source {status_mw[0]}, counter {status_counter.info}"

        if initialized:
            self.settings.child("address").setValue(
                self.mw_controller.get_address())
            self.settings.child("power").setValue(
                self.mw_controller.get_power().magnitude)
            self.update_x_axis()
            
        # Initialize viewers panel with the future type of data
        self.data_grabed_signal_temp.emit(
            [DataFromPlugins(name='ODMR', data=[np.array([0., 0., ...])],
                             dim='Data1D', labels=['ODMR'],
                             x_axis=self.x_axis)])
       
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        DAQ_Move_RSMWsource.close(self)
        DAQ_0DViewer_DAQmx.close(self)
        
    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging, not relevant here.
        kwargs: dict
            others optionals arguments
        """
        if self.sweep_mode:
            self.mw_controller.set_sweep(start=self.start, stop=self.stop,
                                         step=self.step,
                                         power=Q_(self.settings.child("power").value(),
                                                  ureg.dBm))
            self.mw_controller.sweep_on()

        else:
            self.emit_status(ThreadCommand('Update_Status',
                                           ['List not supported yet']))

        ##synchrone version (blocking function)
        data_tot = self.controller.your_method_to_start_a_grab_snap()
        self.data_grabed_signal.emit([DataFromPlugins(name='Mock1', data=data_tot,
                                                      dim='Data1D', labels=['dat0', 'data1'])])
       

    def stop(self):
        """Stop the current grab hardware wise if necessary."""
        self.counter_controller.close()
        self.mw_controller.mw_off()  # when writing your own plugin replace this line
        self.emit_status(ThreadCommand('Update_Status', ['Acquisition stopped']))
        ##############################
        return ''


    def update_x_axis(self):
        """Create the frequency list for the ODMR measurement."""
        if self.nb_ranges == 1:
            # we can use the sweep mode.
            freqs = np.arange(self.start.to(ureg.MHz).magnitude,
                              (self.stop + self.step).to(ureg.MHz).magnitude,
                              self.stepto(ureg.MHz).magnitude)
            self.x_axis = Axis(data=freqs, label="Frequency", units="MHz")
        else:
            self.emit_status(ThreadCommand('Update_Status',
                                           ['Several ranges not supported yet']))
        

if __name__ == '__main__':
    main(__file__)
