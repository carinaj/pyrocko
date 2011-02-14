'''Interface to use CRUST2.0 model by Laske, Masters and Reif.

Reference
---------

Please refer to the REM web site if you use this model: 

    http://igppweb.ucsd.edu/~gabi/rem.html

or

Bassin, C., Laske, G. and Masters, G., The Current Limits of Resolution for
Surface Wave Tomography in North America, EOS Trans AGU, 81, F897, 2000. A 
description of CRUST 5.1 can be found in: Mooney, Laske and Masters, Crust 5.1:
a global crustal model at 5x5 degrees, JGR, 103, 727-747, 1998.
'''

import numpy as num
import os, sys
import copy
from StringIO import StringIO

LICE, LWATER, LSOFTSED, LHARDSED, LUPPERCRUST, LMIDDLECRUST, LLOWERCRUST, LBELOWCRUST = range(8)

class Crust2Profile:
    '''Representation of a CRUST2.0 key profile.'''
    
    layer_names = ('ice', 'water', 'soft sed.', 'hard sed.', 'upper crust', 'middle crust', 'lower crust')
    
    def __init__(self, ident, name, vp, vs, rho, thickness, elevation):
        self._ident = ident
        self._name = name
        self._vp = vp
        self._vs = vs
        self._rho = rho
        self._thickness = thickness
        self._elevation = elevation
        
    def set_elevation(self, elevation):
        self._elevation = elevation
        
    def set_thickness(self, ilayer, thickness):
        self._thickness[ilayer] = thickness
        
    def elevation(self):
        return self._elevation
    
    def __str__(self):
        
        vvp, vvs, vrho, vthi = self.averages()
        
        return '''type, name:              %s, %s
elevation:               %15.5g
crustal thickness:       %15.5g
average vp, vs, rho:     %15.5g %15.5g %15.5g
mantle ave. vp, vs, rho: %15.5g %15.5g %15.5g

%s''' % (self._ident, self._name, self._elevation, vthi, vvp, vvs, vrho,
    self._vp[LBELOWCRUST],self._vs[LBELOWCRUST],self._rho[LBELOWCRUST],
    '\n'.join( [ '%15.5g %15.5g %15.5g %15.5g   %s' % x for x in zip(
        self._thickness, self._vp[:-1], self._vs[:-1], self._rho[0:-1],
        Crust2Profile.layer_names ) ])
      )
   

    def averages(self):
        '''Get crustal averages for vp, vs and density and total crustal thickness,
      
        Takes into account ice layer.
        Does not take into account water layer.
        '''
        
        vthi = num.sum(self._thickness[3:]) + self._thickness[LICE]
        vvp = num.sum(self._thickness[3:] / self._vp[3:-1]) + self._thickness[LICE] / self._vp[LICE]
        vvs = num.sum(self._thickness[3:] / self._vs[3:-1]) + self._thickness[LICE] / self._vs[LICE]
        vrho = num.sum(self._thickness[3:] * self._rho[3:-1]) + self._thickness[LICE] * self._rho[LICE]
            
        vvp = vthi / vvp
        vvs = vthi / vvs
        vrho = vrho / vthi
    
        return vvp, vvs, vrho, vthi
        
def sa2arr(sa):
    return num.array([ float(x) for x in sa ], dtype=num.float)

def wrap(x, mi, ma):
    if mi <= x and x <= ma: return x
    return x - math.floor((x-mi)/(ma-mi)) * (ma-mi)

def clip(x, mi, ma):
    return min(max(mi,x),ma)

class Crust2:
    
    fn_keys      = 'CNtype2_key.txt'
    fn_elevation = 'CNelevatio2.txt'
    fn_map       = 'CNtype2.txt'
    
    nlo = 180
    nla = 90
    
    def __init__(self, directory=None):
        '''Access CRUST2.0 model.
        
        :param directory: Directory with the data files '%s',
             '%s', and '%s' which contain the CRUST2.0 model data. If this is 
             set to None, builtin CRUST2.0 files are used.''' % (
             Crust2.fn_keys, Crust2.fn_elevation, Crust2.fn_map)
    
        self._directory = directory
        self._typemap = None
        self._load_crustal_model()
        
    def get_profile(self, lat, lon):
        '''Get crustal profile at a specific location.
        
        :param lat lon: latititude and longitude in degrees
        '''
        
        return self._typemap[self._indices(float(lat),float(lon))]
        
    def _indices(self, lat,lon):
        lat = clip(lat, -90., 90.)
        lon = wrap(lon, -180., 180.)
        dlo = 360./Crust2.nlo
        dla = 180./Crust2.nla
        cola = 90.-lat
        ilat = int(cola/dla)
        ilon = int((lon+180.)/dlo)
        return ilat, ilon
        
    def _load_crustal_model(self):

        if self._directory is not None:
            path_keys = os.path.join(self._directory, Crust2.fn_keys)
            f = open(path_keys, 'r')
        else:
            from crust2x2_data import decode, type2_key, type2, elevation
            f = StringIO(decode(type2_key))

        # skip header
        for i in range(5):
            f.readline()
                    
        profiles = {}
        while True:
            line = f.readline()
            if not line:
                break
            ident, name = line.split(None, 1)
            line = f.readline()
            vp = sa2arr(line.split()) * 1000.
            line = f.readline()
            vs = sa2arr(line.split()) * 1000.
            line = f.readline()
            rho = sa2arr(line.split()) * 1000.
            line = f.readline()
            toks = line.split()
            thickness = sa2arr(toks[:-2]) * 1000.
            
            profiles[ident] = Crust2Profile(ident.strip(), name.strip(), vp, vs, rho, thickness, 0.0)
            
        f.close()
        
        if self._directory is not None:
            path_map = os.path.join(self._directory, Crust2.fn_map)
            f = open(path_map, 'r')
        else:
            f = StringIO(decode(type2))

        f.readline() # header
            
        amap = {}
        for ila, line in enumerate(f):
            keys = line.split()[1:]
            for ilo, key in enumerate(keys):
                amap[ila,ilo] = copy.deepcopy(profiles[key])
            
        f.close()
        
        if self._directory is not None:
            path_elevation = os.path.join(self._directory, Crust2.fn_elevation)
            f = open(path_elevation, 'r')
    
        else:
            f = StringIO(elevation)
            
        f.readline()
        for ila, line in enumerate(f):
            for ilo, s in enumerate(line.split()[1:]):
                p = amap[ila,ilo]
                p.set_elevation(float(s))
                if p.elevation() < 0.:
                    p.set_thickness(LWATER, -p.elevation())
        
        f.close()
        
        self._typemap = amap
        
