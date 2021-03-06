# Procedure2.py

# Python Imports
import numpy as np
import pylab as plt
from subprocess import call

# SUAVE Imports
import SUAVE
from SUAVE.Core import Data, Units
from SUAVE.Components.Energy.Networks.Battery_Propeller import Battery_Propeller
from SUAVE.Methods.Propulsion import propeller_design
from SUAVE.Input_Output.Results import  print_parasite_drag,  \
     print_compress_drag, \
     print_engine_data,   \
     print_mission_breakdown, \
     print_weight_breakdown
from SUAVE.Methods.Power.Battery.Sizing import initialize_from_energy_and_power, initialize_from_mass
from SUAVE.Input_Output.OpenVSP import vsp_write
from SUAVE.Methods.Aerodynamics.Fidelity_Zero.Lift.compute_max_lift_coeff import compute_max_lift_coeff
from SUAVE.Optimization.write_optimization_outputs import write_optimization_outputs
#from SUAVE.Input_Output.OpenVSP import vspaero

# Files Imports

import Analyses
import Missions
import Vehicles

# ----------------------------------------------------------------------        
#   Setup
# ----------------------------------------------------------------------   

def setup():
    
    # ------------------------------------------------------------------
    #   Analysis Procedure
    # ------------------------------------------------------------------ 
    
    # size the base config
    procedure = Process()
    procedure.simple_sizing = simple_sizing
    
    # Size the battery and charge it before the mission
    procedure.weights_battery = weights_battery
    # finalizes the data dependencies
    procedure.finalize = finalize
    
    # performance studies
    procedure.missions                   = Process()
    procedure.missions.design_mission    = design_mission

    # post process the results
    procedure.post_process = post_process
        
    return procedure

# ----------------------------------------------------------------------        
#   Target Range Function
# ----------------------------------------------------------------------    

def find_target_range(nexus,mission):
    
    segments = mission.segments
    cruise_altitude = mission.segments['climb_2'].altitude_end
    climb_1  = segments['climb_1']
    climb_2  = segments['climb_2']
  
    descent_1 = segments['descent_1']
    descent_2 = segments['descent_2']

    x_climb_1   = climb_1.altitude_end/np.tan(np.arcsin(climb_1.climb_rate/climb_1.air_speed))
    x_climb_2   = (climb_2.altitude_end-climb_1.altitude_end)/np.tan(np.arcsin(climb_2.climb_rate/climb_2.air_speed))

    x_descent_1 = (climb_5.altitude_end-descent_1.altitude_end)/np.tan(np.arcsin(descent_1.descent_rate/descent_1.air_speed))
    x_descent_2 = (descent_1.altitude_end-descent_2.altitude_end)/np.tan(np.arcsin(descent_2.descent_rate/descent_2.air_speed))
    
    cruise_range = mission.design_range-(x_climb_1+x_climb_2+x_descent_1+x_descent_2)
  
    segments['cruise'].distance = cruise_range
    
    return nexus

# ----------------------------------------------------------------------        
#   Design Mission
# ----------------------------------------------------------------------   
 
def design_mission(nexus):
    
    mission = nexus.missions.base
    mission.design_range = 1500.*Units.nautical_miles
    find_target_range(nexus,mission)
    results = nexus.results
    results.base = mission.evaluate()
    
    return nexus

# ----------------------------------------------------------------------        
#   Sizing
# ----------------------------------------------------------------------    

def simple_sizing(nexus):
    configs=nexus.vehicle_configurations
    base=configs.base
    
    
    #find conditions
    air_speed   = nexus.missions.base.segments['cruise'].air_speed 
    altitude    = nexus.missions.base.segments['climb_2'].altitude_end
    atmosphere  = SUAVE.Analyses.Atmospheric.US_Standard_1976()
    
    freestream  = atmosphere.compute_values(altitude)
    freestream0 = atmosphere.compute_values(6000.*Units.ft)  #cabin altitude
    
    diff_pressure         = np.max(freestream0.pressure-freestream.pressure,0)
    fuselage              = base.fuselages['fuselage']
    fuselage.differential_pressure = diff_pressure 
    
    #now size engine
    mach_number        = air_speed/freestream.speed_of_sound
    
    #now add to freestream data object
    freestream.velocity    = air_speed
    freestream.mach_number = mach_number
    freestream.gravity     = 9.81
    
    conditions             = SUAVE.Analyses.Mission.Segments.Conditions.Aerodynamics()   #assign conditions in form for propulsor sizing
    conditions.freestream  = freestream
    
    for config in configs:
        config.wings.horizontal_stabilizer.areas.reference = (26.0/92.0)*config.wings.main_wing.areas.reference
            
        for wing in config.wings:
            
            wing = SUAVE.Methods.Geometry.Two_Dimensional.Planform.wing_planform(wing)
            wing.areas.exposed  = 0.8 * wing.areas.wetted
            wing.areas.affected = 0.6 * wing.areas.reference
            
        fuselage              = config.fuselages['fuselage']
        fuselage.differential_pressure = diff_pressure 
        
        #turbofan_sizing(config.propulsors['turbofan'], mach_number = mach_number, altitude = altitude)
        #compute_turbofan_geometry(config.propulsors['turbofan'], conditions)
        
    # Change the dynamic pressure based on the, add a factor of safety   
    base.envelope.maximum_dynamic_pressure = nexus.missions.mission.segments.cruise.dynamic_pressure*1.2
    
    # Scale the horizontal and vertical tails based on the main wing area
    #For more or less "normal" looking designs the stabilizer and elevators together should be between 15 to 20% of the wing area. 
    #The fin and rudder together should be around 12 to 15%
    base.wings.horizontal_stabilizer.areas.reference = 0.17 * base.reference_area
    base.wings.vertical_stabilizer.areas.reference   = 0.13 * base.reference_area


    # ------------------------------------------------------------------
    #   Landing Configuration
    # ------------------------------------------------------------------
    landing = nexus.vehicle_configurations.landing
    landing_conditions = Data()
    landing_conditions.freestream = Data()

    # landing weight
    landing.mass_properties.landing = 1.0 * config.mass_properties.takeoff
    
    # Landing CL_max
    altitude   = nexus.missions.base.segments[-1].altitude_end
    atmosphere = SUAVE.Analyses.Atmospheric.US_Standard_1976()
    freestream_landing = atmosphere.compute_values(0.)
    landing_conditions.freestream.velocity           = nexus.missions.base.segments['descent_2'].air_speed
    landing_conditions.freestream.density            = freestream_landing.density
    landing_conditions.freestream.dynamic_viscosity  = freestream_landing.dynamic_viscosity
    CL_max_landing,CDi = compute_max_lift_coeff(landing,landing_conditions)
    landing.maximum_lift_coefficient = CL_max_landing
    
    #Takeoff CL_max
    takeoff = nexus.vehicle_configurations.takeoff
    takeoff_conditions = Data()
    takeoff_conditions.freestream = Data()    
    altitude = nexus.missions.base.airport.altitude
    freestream_takeoff = atmosphere.compute_values(altitude)
   
    takeoff_conditions.freestream.velocity           = nexus.missions.base.segments.climb_1.air_speed
    takeoff_conditions.freestream.density            = freestream_takeoff.density
    takeoff_conditions.freestream.dynamic_viscosity  = freestream_takeoff.dynamic_viscosity 
    max_CL_takeoff, CDi = compute_max_lift_coeff(takeoff,takeoff_conditions) 
    takeoff.maximum_lift_coefficient = max_CL_takeoff
    
    #Base config CL_max
    base = nexus.vehicle_configurations.base
    base_conditions = Data()
    base_conditions.freestream = takeoff_conditions.freestream   
    max_CL_base, CDi = compute_max_lift_coeff(base,base_conditions) 
    base.maximum_lift_coefficient = max_CL_base    
    
    return nexus

# ----------------------------------------------------------------------        
#   Weights
# ----------------------------------------------------------------------    

def weights_battery(nexus):
    
    # Evaluate weights for all of the configurations
    config = nexus.analyses.base
    config.weights.evaluate() 
    
    vec     = nexus.vehicle_configurations.base
    payload = vec.propulsors.network.payload.mass_properties.mass  
    msolar  = vec.propulsors.network.solar_panel.mass_properties.mass
    MTOW    = vec.mass_properties.max_takeoff
    empty   = vec.weight_breakdown.empty
    mmotor  = vec.propulsors.network.motor.mass_properties.mass
    
    # Calculate battery mass
    batmass = MTOW - empty - payload - msolar -mmotor
    bat     = vec.propulsors.network.battery
    #initialize_from_mass(bat,batmass)
    #vec.propulsors.network.battery.mass_properties.mass = batmass
        
    # Set Battery Charge
    maxcharge = nexus.vehicle_configurations.base.propulsors.network.battery.max_energy
    charge    = maxcharge
    
    nexus.missions.base.segments['climb_1'].battery_energy = charge 
    
       
    return nexus

# ----------------------------------------------------------------------
#   Finalizing Function
# ----------------------------------------------------------------------    

def finalize(nexus):
    
    nexus.analyses.finalize()   
    
    return nexus

# ----------------------------------------------------------------------
#   Post Process results to give back to the optimizer
# ----------------------------------------------------------------------   

def post_process(nexus):
    
    # Unpack data
    vehicle                           = nexus.vehicle_configurations.base
    results                           = nexus.results
    res = nexus.results.mission.segments.cruise.conditions
    summary                           = nexus.summary
    missions                          = nexus.missions  
    nexus.total_number_of_iterations +=1
    
    #throttle in design mission
    max_throttle = 0
    for segment in results.base.segments.values():
        max_segment_throttle = np.max(segment.conditions.propulsion.throttle[:,0])
        if max_segment_throttle > max_throttle:
            max_throttle = max_segment_throttle
            
    summary.max_throttle = max_throttle
    
    # CL max constraint, it is the same throughout the mission
    CL = res.aerodynamics.lift_coefficient[0]
    
    # Pack up
    summary.CL                = 1.2 - CL
    
    
    #when you run want to output results to a file
    filename = 'results.txt'
    write_optimization_outputs(nexus, filename)
    
    return nexus


