from __future__ import absolute_import

"""

"""

import numpy as np
import sunpy

#Prepares polynomial coefficients out to a certain order, outputs as ndarray
def prep_coeff(coeff, order=2):
    new_coeff = np.zeros(order+1)
    if type(coeff) == list or type(coeff) == np.ndarray:
        size = min(len(coeff),len(new_coeff))
        new_coeff[0:size] = coeff[0:size]
    else:
        new_coeff[0] = coeff
    return new_coeff

def simulate_raw(params):
    from sunpy.util import util
    import datetime
    from scipy.special import erf

    cadence = params["cadence"]
    direction = 90.+params["direction"]
    
    width_coeff = prep_coeff(params["width"])
    wave_thickness_coeff = prep_coeff(params["wave_thickness"])
    wave_normalization_coeff = prep_coeff(params["wave_normalization"])
    speed_coeff = prep_coeff(params["speed"])
    
    lat_min = params["lat_min"]
    lat_max = params["lat_max"]
    lat_bin = params["lat_bin"]
    lon_min = params["lon_min"]
    lon_max = params["lon_max"]
    lon_bin = params["lon_bin"]

    #This roundabout approach recalculates lat_bin and lon_bin to produce equally
    #sized bins to exactly span the min/max ranges
    lat_num = int(round((lat_max-lat_min)/lat_bin))
    lat_edges, lat_bin = np.linspace(lat_min,lat_max,lat_num+1,retstep=True)
    lon_num = int(round((lon_max-lon_min)/lon_bin))
    lon_edges, lon_bin = np.linspace(lon_min,lon_max,lon_num+1,retstep=True)
    
    #Propagates from 90. down to lat_min, irrespective of lat_max
    p = np.poly1d([speed_coeff[2]/3.,speed_coeff[1]/2.,speed_coeff[0],-(90.-lat_min)])
    
    #Will fail if wave does not propogate all the way to lat_min
    duration = p.r[np.logical_and(p.r.real > 0,p.r.imag == 0)][0]
    
    steps = int(duration/cadence)+1
    if steps > params["max_steps"]:
        steps = params["max_steps"]
    
    #Maybe used np.poly1d() instead to do the polynomial calculation?
    time = np.arange(steps)*cadence
    time_powers = np.vstack((time**0,time**1,time**2))
    
    width = np.dot(width_coeff,time_powers).ravel()
    wave_thickness = np.dot(wave_thickness_coeff,time_powers).ravel()
    wave_normalization = np.dot(wave_normalization_coeff,time_powers).ravel()
    
    #Propagates from 90., irrespective of lat_max
    wave_peak = 90.-(p(time)+(90.-lat_min))
    
    wave_maps = []
    
    dict_header = {
        "cdelt1": lon_bin,
        "naxis1": lon_num,
        "crval1": lon_min,
        "crpix1": 0,
        "cunit1": "deg",
        "ctype1": "HG",
        "cdelt2": lat_bin,
        "naxis2": lat_num,
        "crval2": lat_min,
        "crpix2": 0,
        "cunit2": "deg",
        "ctype2": "HG",
        "hglt_obs": 0,
        "hgln_obs": 0,
        "rsun_obs": 963.879683,
        "rsun_ref": 696000000.0,
        "dsun_obs": 148940609626.98
    }
    
    header = sunpy.map.MapHeader(dict_header)
    
    for istep in xrange(steps):
        #Gaussian profile in longitudinal direction
        #Does not take into account spherical geometry (i.e., change in area element)
        if (wave_thickness[istep] <= 0):
            print("ERROR: wave thickness is non-physical!")
        z = (lat_edges-wave_peak[istep])/wave_thickness[istep]
        wave_1d = wave_normalization[istep]*((erf(np.roll(z,-1)/np.sqrt(2))-erf(z/np.sqrt(2)))/2)[0:lat_num]
        
        wave_lon_min = direction-width[istep]/2
        wave_lon_max = direction+width[istep]/2

        if (width[istep]< 360.):
            wave_lon_min_mod = ((wave_lon_min+180.) % 360.)-180. #does this need to be np.remainder() instead?
            wave_lon_max_mod = ((wave_lon_max+180.) % 360.)-180.
            
            index1 = np.arange(lon_num+1)[np.roll(lon_edges,-1) > min(wave_lon_min_mod,wave_lon_max_mod)][0]
            index2 = np.roll(np.arange(lon_num+1)[lon_edges < max(wave_lon_min_mod,wave_lon_max_mod)],1)[0]
    
            wave_lon = np.zeros(lon_num)
            wave_lon[index1+1:index2] = 1.
            #Possible weirdness if index1 == index2
            wave_lon[index1] += (lon_edges[index1+1]-min(wave_lon_min_mod,wave_lon_max_mod))/lon_bin
            wave_lon[index2] += (max(wave_lon_min_mod,wave_lon_max_mod)-lon_edges[index2])/lon_bin
            
            if (wave_lon_min_mod > wave_lon_max_mod):
                wave_lon = 1.-wave_lon
        else:
            wave_lon = np.ones(lon_num)
        
        #Could be accomplished with np.dot() without casting as matrices?
        wave = np.mat(wave_1d).transpose()*np.mat(wave_lon)
        
        wave_maps += [sunpy.map.BaseMap(wave, header)]
        wave_maps[istep].name = "Simulation"
        wave_maps[istep].date = util.anytim("2011-11-11")+datetime.timedelta(0,istep*cadence)
    
    return wave_maps

#Transformation is partially hard-coded, so use with caution
def transform(params,wave_maps):
    from sunpy.wcs import wcs
    from scipy.interpolate import griddata
    
    epi_lat = params["epi_lat"]
    epi_lon = params["epi_lon"]
    
    hpcx_min = params["hpcx_min"]
    hpcx_max = params["hpcx_max"]
    hpcx_bin = params["hpcx_bin"]
    hpcy_min = params["hpcy_min"]
    hpcy_max = params["hpcy_max"]
    hpcy_bin = params["hpcy_bin"]
    
    hpcx_num = int(round((hpcx_max-hpcx_min)/hpcx_bin))
    hpcy_num = int(round((hpcy_max-hpcy_min)/hpcy_bin))
    
    wave_maps_transformed = []
    
    dict_header = {
        "cdelt1": hpcx_bin,
        "naxis1": hpcx_num,
        "crval1": hpcx_min,
        "crpix1": 0,
        "cunit1": "arcsec",
        "ctype1": "HPC",
        "cdelt2": hpcy_bin,
        "naxis2": hpcy_num,
        "crval2": hpcy_min,
        "crpix2": 0,
        "cunit2": "arcsec",
        "ctype2": "HPC",
        "hglt_obs": 0,
        "hgln_obs": 0,
        "rsun_obs": 963.879683,
        "rsun_ref": 696000000.0,
        "dsun_obs": 148940609626.98
    }
    
    header = sunpy.map.MapHeader(dict_header)

    for current_wave_map in wave_maps:
        #print("Transforming map at "+str(current_wave_map.date))
        
        #Could instead use linspace or mgrid?
        lon = np.arange(current_wave_map.xrange[0]+0.5*current_wave_map.header["cdelt1"],current_wave_map.xrange[1],current_wave_map.header["cdelt1"])
        lat = np.arange(current_wave_map.yrange[0]+0.5*current_wave_map.header["cdelt2"],current_wave_map.yrange[1],current_wave_map.header["cdelt2"])
        lon_grid,lat_grid = np.meshgrid(lon,lat)
        
        #xx, yy = wcs.convert_hg_hpc(current_wave_map.header, lon_grid, lat_grid, units="arcsec", occultation=True)
        x, y, z = wcs.convert_hg_hcc_xyz(current_wave_map.header, lon_grid, lat_grid)
        coslat = np.cos(-np.deg2rad(90.-epi_lat))
        sinlat = np.sin(-np.deg2rad(90.-epi_lat))
        coslon = np.cos(-np.deg2rad(epi_lon))
        sinlon = np.sin(-np.deg2rad(epi_lon))
        xp = coslon*x-sinlon*(-sinlat*y+coslat*z)
        yp = coslat*y+sinlat*z
        zp = sinlon*x+coslon*(-sinlat*y+coslat*z)
        xx, yy = wcs.convert_hcc_hpc(current_wave_map.header, xp, yp)
        xx *= 3600
        yy *= 3600
        
        #Coordinate positions (HPC) with corresponding map data
        points = np.vstack((xx.ravel(), yy.ravel())).T
        values = np.array(current_wave_map).ravel()
        
        #Destination HPC grid
        #Could instead use linspace or mgrid?
        hpcx = np.arange(hpcx_min+0.5*hpcx_bin,hpcx_max,hpcx_bin)
        hpcy = np.arange(hpcy_min+0.5*hpcy_bin,hpcy_max,hpcy_bin)
        hpcx_grid,hpcy_grid = np.meshgrid(hpcx,hpcy)
        
        #2D interpolation
        #grid = griddata(points[np.isfinite(xx.ravel()),:], values[np.isfinite(xx.ravel())], (grid_x, grid_y), method="linear")
        grid = griddata(points[zp.ravel() >= 0], values[zp.ravel() >= 0], (hpcx_grid, hpcy_grid), method="linear")
        
        transformed_wave_map = sunpy.map.BaseMap(grid, header)
        transformed_wave_map.name = current_wave_map.name
        transformed_wave_map.date = current_wave_map.date
        wave_maps_transformed += [transformed_wave_map]

    return wave_maps_transformed

def add_noise(params,wave_maps):
    wave_maps_noise = []
    for current_wave_map in wave_maps:
        wave_maps_noise += [current_wave_map]
    return wave_maps_noise

def simulate(params):
    wave_maps_raw = simulate_raw(params)
    wave_maps_transformed = transform(params,wave_maps_raw)
    wave_maps_noise= add_noise(params,wave_maps_transformed)
    return wave_maps_noise