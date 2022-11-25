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
# shared UnitRegistry from pint initialized in __init__.py
# from pymodaq_plugins_s2qt_odmr import ureg, Q_


class DAQ_1DViewer_ODMR(DAQ_0DViewer_DAQmx, DAQ_Move_RSMWsource):
    """ Plugin generating a hybrid 1D viewer based on a RS MW source
    and a NI card based counter to perform ODMR measurement of
    fluorescent defects. This object inherits all functionality to
    communicate with PyMoDAQ Module, MW source and NI card through
    inheritance of DAQ_0DViewer_DAQmx and DAQ_Move_RSMWsource.
    """
    params = comon_parameters + [
        ## TODO for your custom plugin
        # elements to be added here as dicts in order to control your custom stage
        ############
        ]

    def __init__(self, parent=None, params_state=None):
        DAQ_0DViewer_DAQmx.__init__(self, parent, params_state)
        DAQ_Move_RSMWsource.__init__(self, parent, params_state)
        

    def ini_attributes(self):
        self.mw_controller = None
        self.counter_controller = None

        self.x_axis = None
        

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector
        settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value
            has been changed by the user
        """
        ## TODO for your custom plugin
        if param.name() == "a_parameter_you've_added_in_self.params":
           self.controller.your_method_to_apply_this_param_change()
#        elif ...
        ##
        

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
        ## TODO for your custom plugin
        # get the x_axis (you may want to to this also in the commit settings if x_axis may have changed
        if initialized:
            data_x_axis = np.linspace(2850, 2890, 50)
            self.x_axis = Axis(data=data_x_axis, label='', units='')
        # TODO for your custom plugin. Initialize viewers pannel with the future type of data
        self.data_grabed_signal_temp.emit(
            [DataFromPlugins(name='ODMR', data=[np.array([0., 0., ...])],
                             dim='Data1D', labels=['ODMR'],
                             x_axis=self.x_axis)])
        # note: you could either emit the x_axis once (or a given place in the code) using self.emit_x_axis() as shown
        # above. Or emit it at every grab filling it the x_axis key of DataFromPlugins)
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
            Number of hardware averaging (if hardware averaging is possible, self.hardware_averaging should be set to
            True in class preamble and you should code this implementation)
        kwargs: dict
            others optionals arguments
        """
        ## TODO for your custom plugin

        ##synchrone version (blocking function)
        data_tot = self.controller.your_method_to_start_a_grab_snap()
        self.data_grabed_signal.emit([DataFromPlugins(name='Mock1', data=data_tot,
                                                      dim='Data1D', labels=['dat0', 'data1'])])
        # note: you could either emit the x_axis once (or a given place in the code) using self.emit_x_axis() as shown
        # above. Or emit it at every grab filling it the x_axis key of DataFromPlugins, not shown here)

        ##asynchrone version (non-blocking function with callback)
        self.controller.your_method_to_start_a_grab_snap(self.callback)
        #########################################################


    def callback(self):
        """optional asynchrone method called when the detector has finished its acquisition of data"""
        data_tot = self.controller.your_method_to_get_data_from_buffer()
        self.data_grabed_signal.emit([DataFromPlugins(name='Mock1', data=data_tot,
                                                      dim='Data1D', labels=['dat0', 'data1'])])

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        ## TODO for your custom plugin
        raise NotImplemented  # when writing your own plugin remove this line
        self.controller.your_method_to_stop_acquisition()  # when writing your own plugin replace this line
        self.emit_status(ThreadCommand('Update_Status', ['Some info you want to log']))
        ##############################
        return ''


if __name__ == '__main__':
    main(__file__)
