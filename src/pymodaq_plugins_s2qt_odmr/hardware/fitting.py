import numpy as np
#import lmfit

class ODMRFitting:
    def __init__(self):
        self._list_functions = ["Single lorentzian", "Single gaussian", "Double lorentzian",
                                "Double gaussian", "N14", "N15"]

    @classmethod
    def list_functions(cls):
        return  ["Single lorentzian", "Single gaussian", "Double lorentzian",
                                "Double gaussian", "N14", "N15"]

    def set_fit_function(self, fit_function):
        if not fit_function in self._list_functions:
            print("Unknown function!")
            return
        else:
            self.fit_function = fit_function 
