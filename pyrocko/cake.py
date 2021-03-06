'''Classical seismic ray theory for layered earth models (*layer cake* models).

This module can be used to e.g. calculate arrival times, ray paths, reflection
and transmission coefficients, take-off and incidence angles and geometrical
spreading factors for arbitrary seismic phases. Computations are done for a
spherical earth, even though the module name may suggests something flat.

The main classes defined in this module are:

* :py:class:`Material` - Defines an isotropic elastic material.
* :py:class:`PhaseDef` - Defines a seismic phase arrival / wave propagation history.
* :py:class:`Leg` - Continuous propagation in a :py:class:`PhaseDef`.
* :py:class:`Knee` - Conversion/reflection in a :py:class:`PhaseDef`.
* :py:class:`LayeredModel` - Representation of a layer cake model.
* :py:class:`Layer` - A layer in a :py:class:`LayeredModel`.
 
   * :py:class:`HomogeneousLayer` - A homogeneous :py:class:`Layer`.
   * :py:class:`GradientLayer` - A gradient :py:class:`Layer`.

* :py:class:`Discontinuity` - A discontinuity in a :py:class:`LayeredModel`.

   * :py:class:`Interface` - A :py:class:`Discontinuity` between two :py:class:`Layer` instances.
   * :py:class:`Surface` - The surface :py:class:`Discontinuity` on top of a :py:class:`LayeredModel`.

* :py:class:`RayPath` - A fan of rays running through a common sequence of layers / interfaces.
* :py:class:`Ray` - A specific ray with a specific (ray parameter, distance, arrival time) choice.
* :py:class:`RayElement` - An element of a :py:class:`RayPath`.

   * :py:class:`Straight` - A ray segment representing propagation through one :py:class:`Layer`.
   * :py:class:`Kink` - An interaction of a ray with a :py:class:`Discontinuity`.
'''


import sys, copy, inspect, math, cmath, operator
from pyrocko import util
from scipy.optimize import bisect
from scipy.interpolate import fitpack
import numpy as num

ZEPS = 0.01
P = 1
S = 2
DOWN = 4
UP = -4

r2d = 180./math.pi
d2r = 1./r2d
km = 1000.


class InvalidArguments(Exception):
    pass

class Material:
    '''Isotropic elastic material.

    :param vp: P-wave velocity [m/s]
    :param vs: S-wave velocity [m/s]
    :param rho: density [kg/m^3]
    :param qp: P-wave attenuation Qp
    :param qs: S-wave attenuation Qs
    :param poisson: Poisson ratio
    :param lame: tuple with Lame parameter `lambda` and `shear modulus` [Pa]
    :param qk: bulk attenuation Qk
    :param qmu: shear attenuation Qmu

    If no velocities and no lame parameters are given, standard crustal values of vp = 5800 m/s and vs = 3200 m/s are used.
    If no Q values are given, standard crustal values of qp = 1456 and qs = 600 are used.

    Everything is in SI units (m/s, Pa, kg/m^3) unless explicitly stated.

    The main material properties are considered independant and are accessible as attributes (it is allowed to assign to these):

        .. py:attribute:: vp, vs, rho, qp, qs

    Other material properties are considered dependant and can be queried by instance methods.
    '''

    def __init__(self, vp=None, vs=None, rho=2600., qp=None, qs=None, poisson=None, lame=None, qk=None, qmu=None):

        parstore_float(locals(), self, 'vp', 'vs', 'rho', 'qp', 'qs')

        if vp is not None and vs is not None:
            if poisson is not None or lame is not None:
                raise InvalidArguments('If vp and vs are given, poisson ratio and lame paramters should not be given.')

        elif vp is None and vs is None and lame is None:
            self.vp = 5800.
            if poisson is None:
                poisson = 0.25
            self.vs = self.vp / math.sqrt(2.0*(1.0-poisson)/(1.0-2.0*poisson))

        elif vp is None and vs is None and lame is not None:
            if poisson is not None:
                raise InvalidArguments('Poisson ratio should not be given, when lame parameters are given.')
            lam, mu = float(lame[0]), float(lame[1])
            self.vp = math.sqrt((lam + 2.0*mu)/rho)
            self.vs = math.sqrt(mu/rho)

        elif vp is not None and vs is None:
            if poisson is None:
                poisson = 0.25
            if lame is not None:
                raise InvalidArguments('If vp is given, Lame parameters should not be given.')
            poisson = float(poisson)
            self.vs = vp / math.sqrt(2.0*(1.0-poisson)/(1.0-2.0*poisson))
        
        elif vp is None and vs is not None:
            if poisson is None:
                poisson = 0.25
            if lame is not None:
                raise InvalidArguments('If vs is given, Lame parameters should not be given.')
            poisson = float(poisson)
            self.vp = vs * math.sqrt(2.0*(1.0-poisson)/(1.0-2.0*poisson))
    
        else:
            raise InvalidArguments('Invalid combination of input parameters in material definition.')

        if qp is not None or qs is not None:
            if not (qk is None and qmu is None):
                raise InvalidArguments('if qp or qs are given, qk and qmu should not be given.')
            if qp is None:
                self.qp = 1456.
            if qs is None:
                self.qs = 600.
        
        elif qp is None and qs is None and qk is None and qmu is None:
            self.qp = 1456.
            self.qs = 600.

        elif qp is None and qs is None and qk is not None and qmu is not None:
            l = (4.0/3.0)*(self.vs/self.vp)**2
            self.qp = 1.0 / (l*(1.0/qmu) + (1-l)*(1.0/qk))
            self.qs = qmu
        else:
            raise InvalidArguments('Invalid combination of input parameters in material definition.')
    
    def astuple(self):
        '''Get independant material properties as a tuple.
        
        Returns a tuple with ``(vp, vs, rho, qp, qs)``.
        '''
        return self.vp, self.vs, self.rho, self.qp, self.qs

    def __eq__(self, other):
        return self.astuple() == other.astuple()

    def lame(self):
        '''Get Lame's parameter lambda and shear modulus.'''
        mu = self.vs**2 * self.rho
        lam = self.vp**2 * self.rho - 2.0*mu
        return lam, mu

    def lame_lambda(self):
        '''Get Lame's parameter lambda.
        
        Returned units are [Pa].
        '''
        lam, _ = self.lame()
        return lam

    def shear_modulus(self):
        '''Get shear modulus.
        
        Returned units are [Pa].
        '''
        return self.vs**2 * self.rho

    def poisson(self):
        '''Get Poisson's ratio.'''
        lam, mu = self.lame()
        return lam / (2.0*(lam+mu))
   
    def bulk(self):
        '''Get bulk modulus.'''
        lam, mu = self.lame()
        return lam + 2.0*mu/3.0

    def youngs(self):
        '''Get Young's modulus.'''
        lam, mu = self.lame()
        return mu * (3.0*lam + 2.0*mu) / (lam+mu)

    def vp_vs_ratio(self):
        '''Get vp/vs ratio.'''
        return self.vp/self.vs

    def qmu(self):
        '''Get shear attenuation coefficient Qmu.'''
        return self.qs

    def qk(self):
        '''Get bulk attenuation coefficient Qk.'''
        l = (4.0/3.0)*(self.vs/self.vp)**2
        return (1.0-l)/((1.0/self.qp) - l*(1.0/self.qs))

    def _rayleigh_equation(self, cr):
        cr_a = (cr/self.vp)**2
        cr_b = (cr/self.vs)**2
        if cr_a > 1.0 or cr_b > 1.0:
            return None
        
        return (2.0-cr_b)**2 - 4.0 * math.sqrt(1.0-cr_a) * math.sqrt(1.0-cr_b)

    def rayleigh(self):
        '''Get rayleigh velocity assuming a homogenous halfspace.
        
        Returned units are [m/s].'''
        return bisect(self._rayleigh_equation, 0.001*self.vs, self.vs)

    def describe(self):
        '''Get a readable listing of the material properties.'''
        template = '''
P wave velocity     [km/s]    : %12g
S wave velocity     [km/s]    : %12g
P/S wave vel. ratio           : %12g     
Lame lambda         [GPa]     : %12g
Lame shear modulus  [GPa]     : %12g
Poisson ratio                 : %12g
Bulk modulus        [GPa]     : %12g
Young's modulus     [GPa]     : %12g
Rayleigh wave vel.  [km/s]    : %12g
Density             [g/cm**3] : %12g
Qp                            : %12g
Qs = Qmu                      : %12g
Qk                            : %12g
'''.strip()

        return template % (self.vp/1000., self.vs/1000., self.vp/self.vs,
                self.lame_lambda()*1e-9, self.shear_modulus()*1e-9, self.poisson(),
                self.bulk()*1e-9, self.youngs()*1e-9, self.rayleigh()/1000., self.rho/1000., self.qp, self.qs, self.qk())

    def __str__(self):
        vp, vs, rho, qp, qs = self.astuple()
        return '%10g km/s  %10g km/s %10g g/cm^3 %10g %10g' % (vp/1000., vs/1000., rho/1000., qp, qs)

    def __repr__(self):
        return 'Material(vp=%s, vs=%s, rho=%s, qp=%s, qs=%s)' % \
                tuple( repr(x) for x in (self.vp, self.vs, self.rho, self.qp, self.qs) )


class Leg:
    '''Represents a continuous piece of wave propagation in a :py:class:`PhaseDef`.
    
     **Attributes:**

     To be considered as read-only.

        .. py:attribute:: departure
        
           One of the constants :py:const:`UP` or :py:const:`DOWN` indicating upward or downward departure. 

        .. py:attribute:: mode

           One of the constants :py:const:`P` or :py:const:`S`, indicating the propagation mode.

        .. py:attribute:: depthmin

           `None`, a number (a depth in [m]) or a string (an interface name), minimum depth.

        .. py:attribute:: depthmax

           `None`, a number (a depth in [m]) or a string (an interface name), maximum depth.
        
    '''
    
    def __init__(self, departure=None, mode=None):
        self.departure = departure
        self.mode = mode
        self.depthmin = None
        self.depthmax = None

    def set_depthmin(self, depthmin):
        self.depthmin = depthmin
    
    def set_depthmax(self, depthmax):
        self.depthmax = depthmax

    def __str__(self):
        def sd(d):
            if isinstance(d, float):
                return '%g km' % (d/km)
            else:
                return 'interface %s' % d
        
        s = '%s mode propagation, departing %s' % (smode(self.mode).upper(), {UP: 'upward', DOWN: 'downward'}[self.departure])
        sc = []
        if self.depthmax is not None:
            sc.append('deeper than %s' %  sd(self.depthmax))
        if self.depthmin is not None:
            sc.append('shallower than %s' % sd(self.depthmin))
        
        if sc:
            s = s + ' (may not propagate %s)' % ' or '.join(sc)

        return s

class InvalidKneeDef(Exception):
    pass

class Knee:
    '''Represents a change in wave propagation within a :py:class:`PhaseDef`.
   
    **Attributes:**

    To be considered as read-only.

        .. py:attribute:: depth

           Depth at which the conversion/reflection should happen. this can be a string or a number.
    
        .. py:attribute:: direction
           
           One of the constants :py:const:`UP` or :py:const:`DOWN` to indicate the incoming direction. 

        .. py:attribute:: in_mode
        
           One of the constants :py:const:`P` or :py:const:`S` to indicate the type of mode of the incoming wave.

        .. py:attribute:: out_mode

           One of the constants :py:const:`P` or :py:const:`S` to indicate the type of mode of the outgoing wave.

        .. py:attribute:: conversion
        
           Boolean, whether there is a mode conversion involved.

        .. py:attribute:: reflection

           Boolean, whether there is a reflection involved. 
    
    '''

    defaults = dict(depth='surface', direction=UP, conversion=True, reflection=False, in_setup_state=True)
    defaults_surface = dict(depth='surface', direction=UP, conversion=False, reflection=True, in_setup_state=True)
    
    def __init__(self, *args):
        if args:
            self.depth, self.direction, self.reflection, self.in_mode, self.out_mode = args
            self.conversion = self.in_mode != self.out_mode
            self.in_setup_state = False

    def default(self,k):
        depth = self.__dict__.get('depth', 'surface')
        if depth == 'surface':
            return Knee.defaults_surface[k] 
        else:
            return Knee.defaults[k] 

    def __setattr__(self, k, v):
        if self.in_setup_state and k in self.__dict__: 
            raise InvalidKneeDef('%s has already been set' % k)
        else:
            self.__dict__[k] = v

    def __getattr__(self, k):
        if k not in self.__dict__:
            return self.default(k)
    
    def set_modes(self, in_leg, out_leg):

        if out_leg.departure == UP and ((self.direction == UP) == self.reflection):
            raise InvalidKneeDef('cannot enter %s from %s and emit ray upwards' % (
                ['conversion', 'reflection'][self.reflection],
                {UP: 'below', DOWN: 'above'}[self.direction]))

        if out_leg.departure == DOWN and ((self.direction == DOWN) == self.reflection):
            raise InvalidKneeDef('cannot enter %s from %s and emit ray downwards' % (
                ['conversion', 'reflection'][self.reflection],
                {UP: 'below', DOWN: 'above'}[self.direction]))

        if in_leg.mode == out_leg.mode and not self.reflection:
            raise InvalidKneeDef('mode of propagation should change at a conversion')

        self.in_mode = in_leg.mode 
        self.out_mode = out_leg.mode

    def at_surface(self):
        return self.depth == 'surface'

    def matches(self, discontinuity, mode, direction):
        '''Check whether it is relevant to a given combination of interface, propagation mode, and direction.'''

        if isinstance(self.depth, float):
            if abs(self.depth - discontinuity.z) > ZEPS:
                return False
        else:
            if discontinuity.name != self.depth:
                return False

        return self.direction == direction and self.in_mode == mode

    def out_direction(self):
        '''Get outgoing direction.
        
        Returns one of the constants :py:const:`UP` or :py:const:`DOWN`.
        '''

        if self.reflection:
            return - self.direction
        else:
            return self.direction

    def __str__(self):
        x = []
        if self.reflection:
            if self.at_surface():
                x.append('surface')
            else:
                if self.direction == UP:
                    x.append('underside')
                else:
                    x.append('upperside')

        if self.reflection and self.conversion:
            x.append('reflection with conversion from %s to %s' % (smode(self.in_mode), smode(self.out_mode)))
        elif self.reflection:
            x.append('reflection')
        elif self.conversion:
            x.append('conversion from %s to %s' % (smode(self.in_mode), smode(self.out_mode)))

        if isinstance(self.depth, float):
            x.append('at interface in %g km depth' % (self.depth/1000.))
        else:
            if not self.at_surface():
                x.append('at %s' % self.depth)
        
        if not self.reflection:
            if self.direction == UP:
                x.append('on upgoing path')
            else:
                x.append('on downgoing path')

        return ' '.join(x)

class PhaseDefParseError(Exception):
    '''Exception raised when an error occures during parsing of a phase definition string.'''

    def __init__(self, definition, position, exception):
        self.definition = definition
        self.position = position
        self.exception = exception

    def __str__(self):
        return 'Invalid phase definition: "%s" (at character %i: %s)' % (self.definition, self.position+1, str(self.exception))

class PhaseDef:
   
    '''Definition of a seismic phase arrival, based on ray propagation path.

    :param definition: string representation of the phase in cake phase syntax
    
    Seismic phases are conventionally named e.g. P, Pn, PP, PcP, etc. In this
    module a slightly different terminology is adapted, which allows to specify
    arbitrary conversion/reflection histories for seismic phases. The
    conventions used here are inspired by those used in the TauP toolkit, but
    are not completely compatible with those.

    The definition of a seismic phase in the syntax implemented here is a
    string consisting of an alternating sequence of *legs* and *knees*. A *leg*
    here represents seismic wave propagation without any conversion,
    encountering only super-critical reflections. Legs are denoted by ``P``,
    ``p`` or ``S`` or ``s``. The capital letters are used when the take-off of
    the *leg* is in downward direction, while the lower case letter indicate a
    take-off in upward direction. A *knee* is denoted by a string of the form
    ``(INTERFACE)`` where INTERFACE is the name of an interface (which should
    be defined in the models which are used with this phase) or ``DEPTH``,
    where DEPTH is a number, for mode conversions, ``v(INTERFACE)`` or
    ``vDEPTH`` for top-side reflections or ``^(INTERFACE)`` or ``^DEPTH`` for
    underside reflections. When DEPTH is given as a numerical value in [km], the
    interface closest to that depth is chosen. If two legs appear
    consecutively without an explicit *knee*, surface interaction is assumed.
    The string may end with a backslash ``\\``, to indicate that the ray should
    arrive at the receiver from above instead of from below, which is the
    default. It is possible to restrict the maximum and minimum depth of a
    *leg* by appending ``<(INTERFACE)`` or ``<DEPTH`` or ``>(INTERFACE)`` or
    ``>DEPTH`` after the leg character, respectively.
    
    **Examples:**

        * ``P`` - like the classical P, but includes PKP, PKIKP, Pg
        * ``P<(moho)`` - like Pg, but must leave source downwards
        * ``pP`` - leaves source upward, reflects at surface, then travels as P
        * ``P(moho)s`` - conversion from P to S at the Moho on upgoing path
        * ``P(moho)S`` - conversion from P to S at the Moho on downgoing path
        * ``Pv12p`` - P with reflection at 12 km deep interface (or the interface closest to that)
        * ``P^(conrad)P`` - underside reflection of P at the Conrad discontinuity

    **Usage:**

        >>> from pyrocko.cake import PhaseDef
        >>> my_crazy_phase = PhaseDef('pPv(moho)sP\\\\')   # must escape the backslash
        >>> print my_crazy_phase
        Phase definition "pPv(moho)sP\":
         - P mode propagation, departing upward
         - surface reflection
         - P mode propagation, departing downward
         - upperside reflection with conversion from p to s at moho
         - S mode propagation, departing upward
         - surface reflection with conversion from s to p
         - P mode propagation, departing downward
         - arriving at target from above

    .. note::
    
        (1) These conventions might be extended in a way to allow to fix wave
            propagation to SH mode, possibly by specifying SH, or a single
            character (e.g. H) instead of S. This would be benificial for the
            selection of conversion and reflection coefficients, which currently 
            only deal with the P-SV case.

        (2) Need a way to specify headwaves (maybe ``P_(moho)p``).

        (3) To support direct mappings between the classical phase names and
            cake phase names, a way to constrain the turning point depth is 
            needed.

    '''

    classic_defs = {}
    for r in 'mc':
        # PmP PcP and the like:
        for a,b in 'PP PS SS SP'.split():
            classic_defs[a+r+b] = [ '%sv(%s)%s' % (a, {'m': 'moho', 'c': 'cmb'}[r], b.lower() ) ]
       
    for c in 'PS':
        classic_defs[a+'g'] = [ '%s<(moho)' % x for x in (c, c.lower()) ]
        classic_defs[a] = [ '%s<(cmb)' % x for x in (c, c.lower()) ]

    def __init__(self, definition=None):
        
        state = 0
        sdepth = ''
        sinterface = ''
        depthmax = depthmin = None
        depthlim = None
        depthlimtype = None
        sdethmlim = ''
        events = []
        direction_stop = UP
        need_leg = True
        ic = 0
        if definition is not None:
            knee = Knee()
            try:
                for ic, c in enumerate(definition):

                    if state in (0,1):
                        
                        if c in '0123456789.':
                            need_leg = True
                            state = 1
                            sdepth += c
                            continue
                        
                        elif state == 1:
                            knee.depth = float(sdepth)*1000.
                            state = 0

                    if state == 2:
                        if c == ')':
                            knee.depth = sinterface
                            state = 0
                        else:
                            sinterface += c 

                        continue

                    if state in (3,4):

                        if state == 3:
                            if c in '0123456789.':
                                sdepthlim += c
                                continue
                            elif c == '(':
                                state = 4
                                continue
                            else:
                                depthlim = float(sdepthlim)*1000.
                                if depthlimtype == '<':
                                    depthmax = depthlim
                                else:
                                    depthmin = depthlim
                                state = 0

                        elif state == 4:
                            if c == ')':
                                depthlim = sdepthlim
                                if depthlimtype == '<':
                                    depthmax = depthlim
                                else:
                                    depthmin = depthlim
                                state = 0
                                continue
                            else:
                                sdepthlim += c
                                continue

                    if state == 0:

                        if c == '(':
                            need_leg = True
                            state = 2
                            continue

                        elif c in '<>':
                            state = 3
                            depthlim = None
                            sdepthlim = ''
                            depthlimtype = c
                            continue
                        
                        elif c in 'psPS':
                            leg = Leg()
                            if c in 'ps':
                                leg.departure = UP
                            else:
                                leg.departure = DOWN
                            leg.mode = imode(c)

                            if events:
                                in_leg = events[-1]
                                if depthmin is not None:
                                    in_leg.set_depthmin(depthmin)
                                    depthmin = None
                                if depthmax is not None:
                                    in_leg.set_depthmax(depthmax)
                                    depthmax = None
                                
                                if in_leg.mode == leg.mode:
                                    knee.conversion = False
                                else:
                                    knee.conversion = True
                               
                                if not knee.reflection and knee.conversion:
                                    if c in 'ps':
                                        knee.direction = UP
                                    else:
                                        knee.direction = DOWN

                                knee.set_modes(in_leg, leg)
                                knee.in_setup_state = False
                                events.append(knee)
                                knee = Knee()
                                sdepth = ''
                                sinterface = ''


                            events.append(leg)
                            need_leg = False
                            continue

                        elif c == '^':
                            need_leg = True
                            knee.direction = UP
                            knee.reflection = True
                            continue

                        elif c == 'v':
                            need_leg = True
                            knee.direction = DOWN
                            knee.reflection = True
                            continue

                        elif c == '\\':
                            direction_stop = DOWN
                            continue
                            
                        else:
                            raise PhaseDefParseError(definition, ic, 'invalid character: "%s"' % c)
                
                if state == 3:
                    depthlim = float(sdepthlim)*1000.
                    if depthlimtype == '<':
                        depthmax = depthlim
                    else:
                        depthmin = depthlim
                    state = 0

            except (ValueError, InvalidKneeDef), e:
                raise PhaseDefParseError(definition, ic, e)
            

            if state != 0 or need_leg:
                raise PhaseDefParseError(definition, ic, 'unfinished expression')

            if events and depthmin is not None:
                events[-1].set_depthmin(depthmin)
            if events and depthmax is not None:
                events[-1].set_depthmax(depthmax)

        self.definition = definition
        self.events = events
        self.direction_stop = direction_stop
   
    def __iter__(self):
        for ev in self.events:
            yield ev

    def append(self, ev):
        self.events.append(ev)

    def first_leg(self):
        '''Get the first leg in phase definition.'''
        return self.events[0]

    def last_leg(self):
        '''Get the last leg in phase definition.'''
        return self.events[-1]

    def legs(self):
        '''Iterate over the continuous pieces of wave propagation (legs) defined within this phase definition.'''
        return ( leg for leg in self if isinstance(leg, Leg) )

    def knees(self):
        '''Iterate over conversions and reflections (knees) defined within this phase definition.'''
        return ( knee for knee in self if isinstance(knee, Knee) )

    def used_repr(self):
        '''Translate into textual representation (cake phase syntax).'''
        x = []
        for el in self:
            if isinstance(el, Leg):
                if el.departure == UP:
                    x.append(smode(el.mode).lower())
                else:
                    x.append(smode(el.mode).upper())
            else:
                if el.reflection and not el.at_surface():
                    if el.direction == DOWN:
                        x.append('v')
                    else:
                        x.append('^')
                if not el.at_surface():
                    if isinstance(el.depth, float):
                        x.append('%g' % (el.depth/1000.))
                    else:
                        x.append('(%s)' % el.depth)
    
        if self.direction_stop == DOWN:
            x.append('\\')

        return ''.join(x)
   
    def __repr__(self):
        if self.definition is not None:
            return "PhaseDef('%s')" % self.definition
        else:
            return "PhaseDef('%s')" % self.used_repr()

    def __str__(self):
        orig = ''
        used = self.used_repr()
        if self.definition != used:
            orig = ' (entered as "%s")' % self.definition

        sarrive = '\n - arriving at target from %s' % ('below', 'above')[self.direction_stop == DOWN]
        return 'Phase definition "%s"%s:\n - ' % (used, orig) + '\n - '.join(str(ev) for ev in self) + sarrive
        

    def copy(self):
        '''Get a deep copy of it.'''
        return copy.deepcopy(self)

def csswap(x):
    return cmath.sqrt(1.-x**2)

def psv_surface_ind(in_mode, out_mode):
    '''Get indices to select the appropriate element from scatter matrix for free surface.'''

    return (int(in_mode==S), int(out_mode==S))

def psv_surface(material, p, energy=False):
    '''Scatter matrix for free surface reflection/conversions.
   
    :param material: material, object of type :py:class:`Material`
    :param p: flat ray parameter [s/m]
    :param energy: bool, when ``True`` energy normalized coefficients are returned
    :returns: Scatter matrix
    
    The scatter matrix is ordered as follows::

        [[ PP, PS ],
         [ SP, SS ]]

    The formulas given in Aki & Richards are used.
    '''

    vp, vs, rho = material.vp, material.vs, material.rho
    
    sinphi = p * vp
    sinlam = p * vs
    cosphi = csswap( sinphi )
    coslam = csswap( sinlam )
    vsp_term = (1.0/vs**2 - 2.0*p**2) 
    pcc_term = 4.0 * p**2 * cosphi/vp * coslam/vs
    denom = vsp_term**2 + pcc_term

    scatter = num.array([[- vsp_term**2 + pcc_term, 4.0*p*coslam/vp*vsp_term],
            [4.0*p*cosphi/vs*vsp_term, vsp_term**2 - pcc_term ]], dtype=num.complex) / denom

    if not energy:
        return scatter
    else:
        eps = 1e-16
        normvec = num.array([vp*rho*cosphi+eps, vs*rho*coslam+eps])
        escatter = scatter*num.conj(scatter) * num.real((normvec[:,num.newaxis]) / (normvec[num.newaxis,:]))
        return num.real(escatter)

def psv_solid_ind(in_direction, out_direction, in_mode, out_mode):
    '''Get indices to select the appropriate element from scatter matrix for solid-solid interface.'''

    return  (out_direction==DOWN)*2 + (out_mode==S), (in_direction==UP)*2 + (in_mode==S)
    
def psv_solid(material1, material2, p, energy=False):
    '''Scatter matrix for solid-solid interface.
   
    :param material1: material above, object of type :py:class:`Material`
    :param material2: material below, object of type :py:class:`Material` 
    :param p: flat ray parameter [s/m]
    :param energy: bool, when ``True`` energy normalized coefficients are returned
    :returns: Scatter matrix

    The scatter matrix is ordered as follows::

       [[P1P1, S1P1, P2P1, S2P1],
        [P1S1, S1S1, P2S1, S2S1],
        [P1P2, S1P2, P2P2, S2P2],
        [P1S2, S1S2, P2S2, S2S2]]

    The formulas given in Aki & Richards are used.
    '''

    vp1, vs1, rho1 = material1.vp, material1.vs, material1.rho
    vp2, vs2, rho2 = material2.vp, material2.vs, material2.rho
    
    sinphi1 = p * vp1
    cosphi1 = csswap( sinphi1 )
    sinlam1 = p * vs1
    coslam1 = csswap( sinlam1 )
    sinphi2 = p * vp2
    cosphi2 = csswap( sinphi2 )
    sinlam2 = p * vs2
    coslam2 = csswap( sinlam2 )
    
    # from aki and richards
    M = num.array([[ -vp1*p, -coslam1, vp2*p, coslam2 ],
                   [ cosphi1, -vs1*p, cosphi2, -vs2*p ],
                   [ 2.0*rho1*vs1**2*p*cosphi1, rho1*vs1*(1.0-2.0*vs1**2*p**2), 
                     2.0*rho2*vs2**2*p*cosphi2, rho2*vs2*(1.0-2.0*vs2**2*p**2) ],
                   [ -rho1*vp1*(1.0-2.0*vs1**2*p**2), 2.0*rho1*vs1**2*p*coslam1, 
                     rho2*vp2*(1.0-2.0*vs2**2*p**2), -2.0*rho2*vs2**2*p*coslam2 ]], dtype=num.complex)
    N = M.copy()
    N[0] *= -1.0
    N[3] *= -1.0

    scatter = num.dot(num.linalg.inv(M), N)

    if not energy:
        return scatter
    else:
        eps = 1e-16
        if vs1 == 0.:
            vs1 = vp1*1e-16
        if vs2 == 0.:
            vs2 = vp2*1e-16
        normvec = num.array([vp1*rho1*(cosphi1+eps), vs1*rho1*(coslam1+eps), 
                             vp2*rho2*(cosphi2+eps), vs2*rho2*(coslam2+eps)], dtype=num.complex)
        escatter = scatter*num.conj(scatter) * num.real(normvec[:,num.newaxis] / normvec[num.newaxis,:])
        
        return num.real(escatter)

class BadPotIntCoefs(Exception):
    pass

def potint_coefs(c1, c2, r1, r2):  # r2 > r1
    eps = r2*1e-9
    if c1 == 0. and c2 == 0.:
        c1c2 = 1.
    else:
        c1c2 = c1/c2
    b = math.log(c1c2)/math.log((r1+eps)/r2)
    if abs(b) > 10.:
        raise BadPotIntCoefs()
    a = c1/(r1+eps)**b
    return a,b

def imode(s):
    if s.lower() == 'p':
        return P
    elif s.lower() == 's':
        return S

def smode(i):
    if i == P:
        return 'p'
    elif i == S:
        return 's'

class SurfaceReached(Exception):
    pass

class BottomReached(Exception):
    pass

class MaxDepthReached(Exception):
    pass

class MinDepthReached(Exception):
    pass

class Trapped(Exception):
    pass

class CannotPropagate(Exception):
    def __init__(self, direction, ilayer):
        Exception.__init__(self)
        self._direction = direction
        self._ilayer = ilayer

    def __str__(self):
        return 'Cannot enter layer %i from %s' % (self._ilayer, {UP: 'below', DOWN: 'above'}[self._direction])

class Layer:
    '''Representation of a layer in a layered earth model.
    
    :param ztop: depth of top of layer
    :param zbot: depth of bottom of layer
    :param name: name of layer (optional)
    '''

    def __init__(self, ztop, zbot, name=None):
        self.ztop = ztop
        self.zbot = zbot
        self.zmid = ( self.ztop + self.zbot ) * 0.5
        self.name = name

    def _update_potint_coefs(self):
        self._use_potential_interpolation = False
        try:
            self._ppic = potint_coefs(self.mbot.vp, self.mtop.vp, radius(self.zbot), radius(self.ztop))
            self._spic = potint_coefs(self.mbot.vs, self.mtop.vs, radius(self.zbot), radius(self.ztop))
            self._use_potential_interpolation = True
        except BadPotIntCoefs:
            pass

    def potint_coefs(self, mode):
        '''Get coefficients for potential interpolation.
        
        :param mode: mode of wave propagation, :py:const:`P` or :py:const:`S`
        :returns: coefficients ``(a,b)``
        '''

        if mode == P:
            return self._ppic
        else:
            return self._spic

    def contains(self, z):
        '''Tolerantly check if a given depth is within the layer (including boundaries).'''

        return self.ztop <= z <= self.zbot or self.at_bottom(z) or self.at_top(z)

    def inner(self, z):
        '''Tolerantly check if a given depth is within the layer (not including boundaries).'''
        
        return self.ztop <= z <= self.zbot and not self.at_bottom(z) and not self.at_top(z)

    def at_bottom(self, z):
        '''Tolerantly check if given depth is at the bottom of the layer.'''

        return abs(self.zbot - z) < ZEPS

    def at_top(self, z):
        '''Tolerantly check if given depth is at the top of the layer.'''
        return abs(self.ztop - z) < ZEPS

    def pflat_top(self, p):
        '''Convert spherical ray parameter to local flat ray parameter for top of layer.'''
        return p / (earthradius-self.ztop)

    def pflat_bottom(self, p):
        '''Convert spherical ray parameter to local flat ray parameter for bottom of layer.'''
        return p / (earthradius-self.zbot)

    def pflat(self, p, z):
        '''Convert spherical ray parameter to local flat ray parameter for given depth.'''
        return p / (earthradius-z)
    
    def xt_potint(self, p, mode, zpart=None):
        '''Get travel time and distance for for traversal with given mode and ray parameter.
        
        :param p: ray parameter (spherical)
        :param mode: mode of propagation (:py:const:`P` or :py:const:`S`)
        :param zpart: if given, tuple with two depths to restrict computation
            to a part of the layer

        This implementation uses analytic formulas valid for a spherical earth
        in the case where the velocity c within the layer is given by potential
        interpolation of the form 

            c(z) = a*z^b
        '''
        utop, ubot = self.us(mode)
        a,b = self.potint_coefs(mode)
        ztop = self.ztop
        zbot = self.zbot
        if zpart is not None:
            utop = self.u(mode, zpart[0])
            ubot = self.u(mode, zpart[1])
            ztop, zbot = zpart
            utop = 1./(a*(earthradius-ztop)**b)
            ubot = 1./(a*(earthradius-zbot)**b)
        
        r1 = radius(zbot)
        r2 = radius(ztop)
        eta1 = r1 * ubot
        eta2 = r2 * utop
        if b != 1:
            def cpe(eta):
                return num.arccos(num.minimum(p/num.maximum(eta,p/2),1.0))
            def sep(eta):
                return num.sqrt(num.maximum(eta**2 - p**2, 0.0))

            x = (cpe(eta2)-cpe(eta1))/(1-b)
            t = (sep(eta2)-sep(eta1))/(1-b)
        else:
            lr = math.log(r2/r1)
            sap = num.sqrt(1/a**2 - p**2)
            x = p/sap * lr
            t = 1./(a**2 * sap)
       
        if isinstance(x, num.ndarray):
            iturn = num.where(num.logical_or(r2*utop - p < 0, r1*ubot - p < 0))
            x[iturn] *= 2.
            t[iturn] *= 2.
        else:
            if r2*utop - p < 0 or r1*ubot - p < 0:
                x *= 2.
                t *= 2.
        
        x *= r2d

        return x,t

    def test(self, p, mode, z):
        '''Check if wave mode can exist for given ray parameter at given depth within the layer.
        
        Uses potential interpolation.
        '''

        return (self.u(mode, z)*radius(z) - p) >= 0
   
    def zturn_potint(self, p, mode):
        '''Get turning depth for given ray parameter and propagation mode.'''

        a,b = self.potint_coefs(mode)
        r = num.exp(num.log(a*p)/(1-b))
        return earthradius-r

    def propagate(self, p, mode, direction):
        '''Propagate ray through layer.
        
        :param p: ray parameter
        :param mode: propagation mode
        :param direction: in direction (:py:const:`UP` or :py:const:`DOWN`''' 
        if direction == DOWN:
            zin, zout = self.ztop, self.zbot
        else:
            zin, zout = self.zbot, self.ztop

        if not self.test(p, mode, zin):
            raise CannotPropagate(direction, self.ilayer)

        if not self.test(p, mode, zout):
            return -direction
        else:
            return direction

class DoesNotTurn(Exception):
    pass


earthradius = 6371.*1000.
def radius(z):
    return earthradius - z

class HomogeneousLayer(Layer):
    '''Representation of a homogeneous layer in a layered earth model.'''

    def __init__(self, ztop, zbot, m, name=None):
        Layer.__init__(self,ztop, zbot, name=name)
        self.m = m
        self.mtop = m
        self.mbot = m
        self._update_potint_coefs()

    def material(self, z):
        return self.m

    def u(self, mode, z=None):
        if mode == P:
            return 1./self.m.vp
        if mode == S:
            return 1./self.m.vs

    def us(self, mode):
        u = self.u(mode)
        return u, u

    def v(self, mode):
        if mode == P:
            return self.m.vp
        if mode == S:
            return self.m.vs

    def vs(self, mode):
        v = self.v(mode)
        return v, v

    def xt(self, p, mode, zpart=None):
        if self._use_potential_interpolation:
            return self.xt_potint(p, mode, zpart)
        
        u = self.u(mode)
        pflat = self.pflat_bottom(p)
        if zpart is None:
            dz = (self.zbot - self.ztop)
        else:
            dz = abs(zpart[1]-zpart[0])

        u = self.u(mode)
        eps = u*0.001
        denom = num.sqrt(u**2 - pflat**2) + eps

        x = r2d*pflat/(earthradius-self.zmid) * dz / denom 
        t = u**2 * dz / denom
        return x, t

    def zturn(self, p, mode):
        if self._use_potential_interpolation:
            return self.zturn_potint(p,mode)
        
        raise DoesNotTurn()

    def split(self, z):
        upper = HomogeneousLayer(self.ztop, z, self.m, name=self.name)
        lower = HomogeneousLayer(z, self.zbot, self.m, name=self.name)
        upper.ilayer = self.ilayer
        lower.ilayer = self.ilayer
        return upper, lower

    def __str__(self):
        if self.name:
            name = self.name + ' '
        else:
            name = ''

        if self._use_potential_interpolation:
            calcmode = 'P'
        else:
            calcmode = 'H'

        return '  (%i) homogeneous layer %s(%g km - %g km) [%s]\n    %s' % (self.ilayer, name, self.ztop/km, self.zbot/km, calcmode, self.m)

class GradientLayer(Layer):
    '''Representation of a gradient layer in a layered earth model.'''

    def __init__(self, ztop, zbot, mtop, mbot, name=None):
        Layer.__init__(self, ztop, zbot, name=name)
        self.mtop = mtop
        self.mbot = mbot
        self._update_potint_coefs()

    def interpolate(self, z, ptop, pbot):
        return ptop + (z - self.ztop)*(pbot - ptop)/(self.zbot-self.ztop) 

    def material(self, z):
        dtop = self.mtop.astuple()
        dbot = self.mbot.astuple()
        d = [ self.interpolate(z, ptop, pbot) for (ptop, pbot) in zip(dtop,dbot) ]
        return Material(*d)

    def us(self, mode):
        if mode == P:
            return 1./self.mtop.vp, 1./self.mbot.vp
        if mode == S:
            return 1./self.mtop.vs, 1./self.mbot.vs

    def u(self, mode, z):
        if mode == P:
            return 1./self.interpolate(z, self.mtop.vp, self.mbot.vp)
        if mode == S:
            return 1./self.interpolate(z, self.mtop.vs, self.mbot.vs)

    def vs(self, mode):
        if mode == P:
            return self.mtop.vp, self.mbot.vp
        if mode == S:
            return self.mtop.vs, self.mbot.vs

    def v(self, mode, z):
        if mode == P:
            return self.interpolate(z, self.mtop.vp, self.mbot.vp)
        if mode == S:
            return self.interpolate(z, self.mtop.vs, self.mbot.vs)
    
    def xt(self, p, mode, zpart=None):
        if self._use_potential_interpolation:
            return self.xt_potint(p, mode, zpart)

        utop, ubot = self.us(mode)
        b = (1./ubot - 1./utop)/(self.zbot - self.ztop)
        pflat = self.pflat_bottom(p)
        if zpart is not None:
            utop = self.u(mode, zpart[0])
            ubot = self.u(mode, zpart[1])
        
        peps = 1e-16
        pdp = pflat + peps 
        def func(u):
            eta = num.sqrt(num.maximum(u**2 - pflat**2, 0.0))
            xx = eta/u 
            tt = num.where( pflat<=u, num.log(u+eta) - num.log(pdp) - eta/u, 0.0 )
            return xx, tt

        xxtop, tttop = func(utop)
        xxbot, ttbot = func(ubot)

        x =  (xxtop - xxbot)/(b*pdp)
        t =  (tttop - ttbot)/b + pflat*x
      
        if isinstance(x, num.ndarray):
            iturn = num.where(num.logical_or(utop - pflat <= 0, ubot - pflat <= 0))
            x[iturn] *= 2.
            t[iturn] *= 2.
        else:
            if utop - pflat <= 0 or ubot - pflat <= 0:
                x *= 2.
                t *= 2.

        x *= r2d/(earthradius - self.zmid)
        return x, t
   
    def zturn(self, p, mode):
        if self._use_potential_interpolation:
            return self.zturn_potint(p,mode)
        pflat = self.pflat_bottom(p)
        vtop, vbot = self.vs(mode)
        return (1./pflat - vtop) * (self.zbot - self.ztop) / (vbot-vtop) + self.ztop

    def split(self, z):
        mmid = self.material(z)
        upper = GradientLayer(self.ztop, z, self.mtop, mmid, name=self.name)
        lower = GradientLayer(z, self.zbot, mmid, self.mbot, name=self.name)
        upper.ilayer = self.ilayer
        lower.ilayer = self.ilayer
        return upper, lower

    def __str__(self):
        if self.name:
            name = self.name + ' '
        else:
            name = ''

        if self._use_potential_interpolation:
            calcmode = 'P'
        else:
            calcmode = 'G'

        return '  (%i) gradient layer %s(%g km - %g km) [%s]\n    %s\n    %s' % (self.ilayer, name, self.ztop/km, self.zbot/km, calcmode, self.mtop, self.mbot)

class Discontinuity:
    '''Base class for discontinuities in layered earth model.'''

    def __init__(self, z, name=None):
        self.z = z
        self.zbot = z
        self.ztop = z
        self.name = name

class Interface(Discontinuity):
    '''Representation of an interface in a layered earth model.'''

    def __init__(self, z, mabove, mbelow, name=None):
        Discontinuity.__init__(self, z, name)
        self.mabove = mabove
        self.mbelow = mbelow

    def __str__(self):
        if self.name is None:
            return 'interface'
        else:
            return 'interface "%s"' % self.name

    def us(self, mode):
        if mode == P:
            return reci_or_none(self.mabove.vp), reci_or_none(self.mbelow.vp)
        if mode == S:
            return reci_or_none(self.mabove.vs), reci_or_none(self.mbelow.vs)

    def propagate(self, p, mode, direction):
        uabove, ubelow = self.us(mode)
        if direction == DOWN:
            if ubelow is not None and ubelow*radius(self.z) - p >= 0:
                return direction
            else:
                return -direction
        if direction == UP:
            if uabove is not None and uabove*radius(self.z) - p >= 0:
                return direction
            else:
                return -direction
            
    def pflat(self, p):
        return p / (earthradius-self.z)

    def efficiency(self, in_direction, out_direction, in_mode, out_mode, p):
        scatter = psv_solid(self.mabove, self.mbelow, self.pflat(p), energy=True)
        return scatter[psv_solid_ind(in_direction, out_direction, in_mode, out_mode)]

class Surface(Discontinuity):
    '''Representation of the surface discontinuity in a layered earth model.'''

    def __init__(self, z, mbelow):
        Discontinuity.__init__(self, z, 'surface')
        self.z = z
        self.mbelow = mbelow
   
    def propagate(self, p, mode, direction):
        return direction  # no implicit reflection at surface

    def pflat(self, p):
        return p / (earthradius-self.z)

    def efficiency(self, in_direction, out_direction, in_mode, out_mode, p):
        return psv_surface(self.mbelow, self.pflat(p), energy=True)[psv_surface_ind(in_mode, out_mode)]

    def __str__(self):
        return 'surface'

class Walker:
    def __init__(self, elements):
        self._elements = elements
        self._i = 0

    def current(self):
        return self._elements[ self._i ]

    def down(self):
        if self._i < len(self._elements)-1:
            self._i += 1
        else:
            raise BottomReached()

    def up(self):
        if self._i > 0:
            self._i -= 1
        else:
            raise SurfaceReached()

    def goto(self, z, direction=DOWN):

        inew = None
        if direction == DOWN:
            i = 0
            ip = 1
        if direction == UP:
            i = len(self._elements)-1
            ip = -1
        for ii in xrange(len(self._elements)):
            l = self._elements[i]
            if isinstance(l, Layer):
                if l.contains(z):
                    inew = i 
                    break
            i += ip

        if inew != None:
            self._i = inew
        else:
            raise OutOfBounds()


class RayElement(object):
    '''An element of a :py:class:`RayPath`.'''

    def __eq__(self, other):
        return type(self) == type(other) and self.__dict__ == other.__dict__

class Straight(RayElement):
    '''A ray segment representing wave propagation through one :py:class:`Layer`.'''

    def __init__(self, direction_in, direction_out, mode, layer):
        self.mode = mode
        self.direction_in = direction_in
        self.direction_out = direction_out
        self.layer = layer
    
    def angle_in(self, p):
        p = self.pflat_in(p)
        vtop, vbot = self.layer.vs(self.mode)
        if self.direction_in == DOWN:
            return num.arcsin(vtop*p)*r2d
        else:
            return 180.-num.arcsin(vbot*p)*r2d

    def angle_out(self, p):
        p = self.pflat_out(p)
        vtop, vbot = self.layer.vs(self.mode)
        if self.direction_out == DOWN:
            v = vbot
            o = 90.
        else:
            v = vtop
            o = 0.

        return o + num.arcsin(v*p)*r2d

    def pflat_in(self, p):
        return p / (earthradius-self.z_in())

    def pflat_out(self, p):
        return p / (earthradius-self.z_out())

    def z_in(self):
        l = self.layer
        return (l.ztop, l.zbot)[self.direction_in == UP]

    def z_out(self):
        l = self.layer
        return (l.ztop, l.zbot)[self.direction_out == DOWN]

    def zturn(self, p):
        l = self.layer
        return l.zturn(p, self.mode)
    
    def u_in(self):
        return self.layer.us(self.mode)[self.direction_in==UP]

    def u_out(self):
        return self.layer.us(self.mode)[self.direction_out==DOWN]

    def xt(self, p, zpart=None):
        return self.layer.xt(p, self.mode, zpart=zpart)

    def __hash__(self):
        return hash((self.direction_in, self.direction_out, self.mode, id(self.layer)))

class Kink(RayElement):
    '''An interaction of a ray with a :py:class:`Discontinuity`.'''

    def __init__(self, in_direction, out_direction, in_mode, out_mode, discontinuity):
        self.in_direction = in_direction
        self.out_direction = out_direction
        self.in_mode = in_mode
        self.out_mode = out_mode
        self.discontinuity = discontinuity

    def reflection(self):
        return self.in_direction != self.out_direction

    def conversion(self):
        return self.in_mode != self.out_mode

    def efficiency(self, p):
        return self.discontinuity.efficiency(self.in_direction, self.out_direction, self.in_mode, self.out_mode, p)

    def __str__(self):
        r, c = self.reflection(), self.conversion()
        if r and c:
            return '|~'
        if r:
            return '|'
        if c:
            return '~'
        return '_'

    def __hash__(self):
        return hash((self.in_direction, self.out_direction, self.in_mode, self.out_mode, id(self.discontinuity)))

class PRangeNotSet(Exception):
    pass

class RayPath:
    '''Representation of a fan of rays running through a common sequence of layers / interfaces.'''

    def __init__(self, phase, zstart, zstop, redistribute_p=False):
        self.elements = []
        self.phase = phase
        self.zstart = zstart
        self.zstop = zstop
        self.used_phase = None
        self._spline_px = None
        self._spline_pt = None
        self._pmax = None
        self._pmin = None
        self._p = None
        self._redistribute_p = redistribute_p

    def append(self, element):
        self.elements.append(element)

    def _check_have_prange(self):
        if self._pmax is None:
            raise PRangeNotSet()
    
    def set_prange(self, pmin, pmax, dp):
        self._pmin, self._pmax = pmin, pmax
        self._prange_dp = dp

    def set_used_phase(self, phase):
        self.used_phase = phase
  
    def pmax(self):
        '''Get maximum valid ray parameter.'''
        self._check_have_prange()
        return self._pmax

    def pmin(self):
        '''Get minimum valid ray parameter.'''
        self._check_have_prange()
        return self._pmin

    def xmin(self):
        '''Get minimal distance.'''
        self._analyse()
        return self._xmin

    def xmax(self):
        '''Get maximal distance.'''
        self._analyse()
        return self._xmax

    def kinks(self):
        '''Iterate over propagation mode changes (reflections/transmissions).'''
        return ( k for k in self.elements if isinstance(k, Kink) )

    def straights(self):
        '''Iterate over ray segments.'''
        return ( s for s in self.elements if isinstance(s, Straight) )

    def first_straight(self):
        '''Get first ray segment.'''
        for s in self.elements:
            if isinstance(s, Straight):
                return s

    def last_straight(self):
        '''Get last ray segment.'''
        for s in reversed(self.elements):
            if isinstance(s, Straight):
                return s

    def efficiency(self, p):
        '''Get product of all conversion/reflection coefficients encountered on path.'''
        return reduce( operator.mul, (k.efficiency(p) for k in self.kinks()), 1.)

    def spreading(self, p):
        '''Get geometrical spreading factor.'''
        self._check_have_prange()
        dp = self._prange_dp * 0.01
        assert self._pmax - self._pmin > dp

        if p + dp > self._pmax:
            p = p-dp

        x0, t = self.xt(p)
        x1, t = self.xt(p+dp)
        x0 *= d2r
        x1 *= d2r
        dp_dx = dp/(x1-x0)
        
        x = x0
        if x == 0.:
            x = x1
            p = dp

        first = self.first_straight()
        last = self.last_straight()
        return  num.abs(dp_dx) * first.pflat_in(p) / (4.0 * math.pi * num.sin(x) * 
                (earthradius-first.z_in()) * (earthradius-last.z_out())**2 * 
                first.u_in()**2 * num.abs(num.cos(first.angle_in(p)*d2r)) * 
                num.abs(num.cos(last.angle_out(p)*d2r)))
    
    def make_p(self, dp=None, n=None, nmin=None):
        assert dp is None or n is None
        
        if dp is None:
            dp = self._prange_dp
        
        if n is None:
            n = int(round((self._pmax-self._pmin)/dp)) + 1

        if nmin is not None:
            n = max(n, nmin)
            
        ppp = num.linspace(self._pmin, self._pmax, n)
        return ppp

    def xt(self, p):
        '''Calculate distance and traveltime for given ray parameter.'''
        if isinstance(p, num.ndarray):
            sx = num.zeros(p.size)
            st = num.zeros(p.size)
        else:
            sx = 0.0
            st = 0.0

        for s in self.straights():
            x,t = s.xt(p)
            sx += x
            st += t

        return sx, st

    def iter_zxt(self, p):
        sx = num.zeros(p.size)
        st = num.zeros(p.size)
        ok = False
        for s in self.straights():
            yield s.z_in(), sx.copy(), st.copy()
            
            x,t = s.xt(p)
            sx += x
            st += t
            ok = True

        if ok: 
            yield s.z_out(), sx.copy(), st.copy()
    
    def iter_partial_zxt(self, p):
        sx = num.zeros(p.size)
        st = num.zeros(p.size)
        ok = False
        for s in self.straights():
            back = None
            yield filled(s.z_in(), p.size), sx.copy(), st.copy()
            zin, zout = s.z_in(), s.z_out()
            if zin != zout:
                n = 10
                dz = (zout - zin)/n
                for i in xrange(n-1):
                    z = zin + (i+1)*dz
                    x,t = s.xt(p, zpart=sorted([zin, z]))
                    yield filled(z, p.size), sx + x, st + t
            else:
                n = 20 
                zturn = s.zturn(p)
                back = []
                for i in xrange(n):
                    z = zin + (zturn - zin)*num.sin((i+1.0)/n*math.pi/2.0)*0.999
                    x,t = s.xt(p, zpart=[zin, z])
                    yield z, sx + x, st + t
                    back.append((z, x, t))

            x,t = s.xt(p)
            sx += x
            st += t
            
            if back:
                for z,x,t in reversed(back):
                    yield z, sx - x, st - t
            
            ok = True

        if ok: 
            yield filled(s.z_out(), p.size), sx.copy(), st.copy()

    def _analyse(self):
        if self._p is not None:
            return

        p = self.make_p(nmin=10)
        x, t = self.xt(p)
        if self._redistribute_p:
            p = evenize(p,x)
            x, t= self.xt(p)
        self._x, self._t, self._p = x, t, p
        self._xmin, self._xmax = x.min(), x.max()
        self._tmin, self._tmax = t.min(), t.max()
        
        self._monoton_x = monotony(x[1:] - x[:-1])
        self._monoton_t = monotony(t[1:] - t[:-1])
       
    def draft_pxt(self):
        self._analyse()
        return self._p, self._x, self._t

    def interpolate_t2x_linear(self, t):
        self._analyse()
        return interp( t, self._t, self._x, self._monoton_t)

    def interpolate_x2t_linear(self, x):
        self._analyse()
        return interp( x, self._x, self._t, self._monoton_x)

    def interpolate_t2px_linear(self, t):
        self._analyse()
        tp = interp( t, self._t, self._p, self._monoton_t)
        tx = interp( t, self._t, self._x, self._monoton_t)
        return [ (t,p,x) for ((t,p), (_,x)) in zip(tp, tx) ]

    def interpolate_x2pt_linear(self, x):
        self._analyse()
        xp = interp( x, self._x, self._p, self._monoton_x)
        xt = interp( x, self._x, self._t, self._monoton_x)
        return [ (x,p,t) for ((x,p), (_,t)) in zip(xp, xt) ] 

    def update_splines(self):
        self._analyse()
        if self._spline_px is None:
            self._spline_px = fitpack.splrep(self._p,self._x)
            self._spline_pt = fitpack.splrep(self._p,self._t)

    def interpolate_x2pt_spline(self, xs_in):
        self._analyse()
        self.update_splines()
        t,c,k = self._spline_px
        ps = []
        for x_in in xs_in:
            cc = c.copy()
            cc -= x_in
            p = fitpack.sproot((t,cc,k))
            ps.extend(p)
        
        if ps:
            xs = num.atleast_1d(fitpack.splev(ps, self._spline_px))
            ts = num.atleast_1d(fitpack.splev(ps, self._spline_pt))
            return num.transpose((xs,ps,ts))
        else:
            return []
    
    def __eq__(self, other):
        if len(self.elements) != len(other.elements):
            return False

        return all( a == b for a, b in zip(self.elements, other.elements) )

    def __hash__(self):
        return hash(tuple( hash(x) for x in self.elements ) + (self.phase.definition,) )

    def __str__(self):
        x = []
        start_i = None
        end_i = None
        turn_i = None
        def append_layers(si, ei, ti):
            if si == ei and (ti is None or ti == si):
                x.append('%i' % si)
            else:
                if ti is not None:
                    x.append('(%i-%i-%i)' % (si, ti, ei))
                else:
                    x.append('(%i-%i)' % (si, ei))

        for el in self.elements:
            if isinstance(el, Straight):
                if start_i is None:
                    start_i = el.layer.ilayer
                if el.direction_in != el.direction_out:
                    turn_i = el.layer.ilayer
                end_i = el.layer.ilayer
                
            elif isinstance(el, Kink):
                if start_i is not None:
                    append_layers(start_i, end_i, turn_i)
                    start_i = None
                    turn_i = None

                x.append(str(el))
        
        if start_i is not None:
            append_layers(start_i, end_i, turn_i)
       
        su = '(%s)' % self.used_phase.used_repr()
        return '%-15s %-17s %s' % (self.phase.definition, su, ''.join(x))

    def describe(self):
        self._analyse()
        return '%s\n - x range: %g %g\n - t range: %g %g\n - p range: %g %g\n' % (
                self, self._xmin*r2d, self._xmax*r2d, self._tmin, self._tmax, self._pmin, self._pmax)


class Ray:
    '''Representation of a specific ray with a specific (ray parameter, distance, arrival time) choice.
   
    **Attributes:**
   
        .. py:attribute:: path

           :py:class:`RayPath` object containing complete propagation history.

        .. py:attribute:: p

           Ray parameter (spherical) [s/deg]

        .. py:attribute:: x

           Radial distance [deg]

        .. py:attribute:: t

           Traveltime [s]
    '''

    def __init__(self, path, p, x, t):
        self.path = path
        self.p = p
        self.x = x
        self.t = t

    def refine(self):
        x, t = self.path.xt(self.p)
        xeps = self.x/10000.
        count = [ 0 ]
        if abs(self.x - x) > xeps:
            ip = num.searchsorted(self.path._p, self.p)
            assert 0 < ip < self.path._p.size
            pl, ph = self.path._p[ip-1], self.path._p[ip]
            def f(p):
                count[0] += 1
                x, t = self.path.xt(p)
                dx = self.x - x
                if abs(dx) < xeps:
                    return 0.0
                else:
                    return dx
            
            p = bisect(f, pl, ph)
            _, self.t = self.path.xt(p)
            self.p = p

        return count[0]

    def takeoff_angle(self):
        return self.path.first_straight().angle_in(self.p)

    def incidence_angle(self):
        return self.path.last_straight().angle_out(self.p)
    
    def efficiency(self):
        return self.path.efficiency(self.p)

    def spreading(self):
        return self.path.spreading(self.p)

    def surface_sphere(self):
        x1, y1 = 0., earthradius - self.path.zstart
        r2 = earthradius - self.path.zstop
        x2, y2 = r2*math.sin(self.x), r2*math.cos(self.x)
        return ((x2-x1)**2 + (y2-y1)**2)*4.0*math.pi

    def __str__(self, as_degrees=False):
        if as_degrees:
            sd = '%6.3g deg' % self.x
        else:
            sd = '%7.5g km' % (self.x*(d2r*earthradius/km))
        return '%7.5g s/deg %s %6.4g s %5.1f %5.1f %3.0f%% %3.0f%% %s' % (
                self.p/r2d, sd, self.t, self.takeoff_angle(), self.incidence_angle(), 
                100*self.efficiency(), 100*self.spreading()*self.surface_sphere(), self.path)

class DiscontinuityNotFound(Exception):
    def __init__(self, depth_or_name):
        Exception.__init__(self)
        self.depth_or_name = depth_or_name

    def __str__(self):
        return 'Cannot find discontinuity from given depth or name: %s' % self.depth_or_name

class NotPhaseConform(Exception):
    pass

class LayeredModel:
    '''Representation of a layer cake model.
    
    There are several ways to initialize an instance of this class.
    
    1. Use the module function :py:func:`load_model` to read a model from a file.
    2. Create an empty model with the default constructor and append layers and discontinuities with the 
       :py:meth:`append` method (from top to bottom).
    3. Use the constructor :py:meth:`LayeredModel.from_scanlines`, to automatically create the
       :py:class:`Layer` and :py:class:`Discontinuity` objects from a given velocity profile.

    '''

    def __init__(self):
        self._surface_material = None
        self._elements = []
        self.nlayers = 0
        self.walkers = {}

    def zeq(self, z1, z2):
        return abs(z1-z2) < ZEPS

    def append(self, element):
        '''Add a layer or discontinuity at bottom of model.'''

        if self._elements:
            self._elements[-1].below = element
        
        if isinstance(element, Layer):
            element.ilayer = self.nlayers
            self.nlayers += 1

        self._elements.append(element)

    def layers(self, direction=DOWN):
        '''Iterate over all layers of model.
        
        :param direction: direction of traversal :py:const:`DOWN` or :py:const:`UP`.
        '''

        if direction == DOWN:
            return ( el for el in self._elements if isinstance(el, Layer) )
        else:
            return ( el for el in reversed(self._elements) if isinstance(el, Layer) )
    
    def layer(self, z, direction=DOWN):
        '''Get layer for given depth.

        :param z: depth [m]
        :param direction: direction of traversal :py:const:`DOWN` or :py:const:`UP`.
        
        Returns first layer which touches depth `z` (tolerant at boundaries).
        '''

        for l in self.layers(direction):
            if l.contains(z):
                return l

    def walker(self, breaks):
        breaks = tuple(breaks)
        if breaks in self.walkers:
            return self.walkers[breaks]

        elements = list(self._elements)
        for br in breaks:
            for il, l in enumerate(elements):
                if isinstance(l, Layer) and l.inner(br):
                    a,b = l.split(br)    
                    elements[il:il+1] = a,b
                    break
   
        w = Walker(elements)
        self.walkers[breaks] = w
        return w

    def material(self, z, direction=DOWN):
        '''Get material at given depth.
        
        :param z: depth [m]
        :param direction: direction of traversal :py:const:`DOWN` or :py:const:`UP`
        :returns: object of type :py:class:`Material`

        If given depth `z` happens to be at an interface, the material of the first layer with respect to the
        the traversal ordering is returned.
        '''

        l = self.layer(z, direction)
        return l.material(z)

    def discontinuities(self):
        '''Iterate over all discontinuities of the model.'''
        
        return ( el for el in self._elements if isinstance(el, Discontinuity) )

    def discontinuity(self, name_or_z):
        '''Get discontinuity by name or depth.
        
        :param name_or_z: name of discontinuity or depth [m] as float value
        '''
        
        if isinstance(name_or_z, float):
            candi = sorted(self.discontinuities(), key=lambda i: abs(i.z-name_or_z))
        else:
            candi = [ i for i in self.discontinuities() if i.name == name_or_z ]

        if not candi:
            raise DiscontinuityNotFound(name_or_z)

        return candi[0]
        
    def adapt_phase(self, phase):
        '''Adapt a phase definition for use with this model.
        
        This returns a copy of the phase definition, where named discontinuities are replaced
        with the actual depth of these, as defined in the model.
        '''

        phase = phase.copy()
        for knee in phase.knees():
            if knee.depth != 'surface':
                knee.depth = self.discontinuity(knee.depth).z
        for leg in phase.legs():
            if leg.depthmax is not None and isinstance(leg.depthmax, str):
                leg.depthmax = self.discontinuity(leg.depthmax).z

        return phase

    def path(self, p, phase=PhaseDef('P'), zstart=0.0, zstop=0.0):
        '''Get ray path for given ray parameter, phase definition and fixed source and receiver depths.
        
        :param p: ray parameter (spherical) [s/deg]
        :param phase: phase definition (:py:class:`PhaseDef` object)
        :param zstart: source depth [m]
        :param zstop: receiver depth [m]
        :returns: :py:class:`RayPath` object

        If it is not possible to find a solution, an exception of type :py:exc:`NotPhaseConform`, 
        :py:exc:`MinDepthReached`, :py:exc:`MaxDepthReached`, :py:exc:`CannotPropagate`, 
        :py:exc:`BottomReached` or :py:exc:`SurfaceReached` is raised.
        '''
        
        phase = self.adapt_phase(phase)
        knees = phase.knees()
        legs = phase.legs()
        next_knee = next_or_none(knees)
        leg = next_or_none(legs)
        assert leg is not None

        direction = leg.departure
        direction_stop = phase.direction_stop
        mode = leg.mode
        mode_stop = phase.last_leg().mode

        breaks = [ zstart, zstop ]
        walker = self.walker(breaks)
        walker.goto(zstart, -direction)
        current = walker.current()
        z = zstart
        mode_layers = []
        used_phase = PhaseDef()
        used_phase.append(Leg(direction, mode))
        path = RayPath(phase, zstart, zstop)
        trapdetect = set()
        while True:
            if isinstance(current, Discontinuity):
                if next_knee is None: # detect trapped wave
                    k = (id(current), direction, mode)
                    if k in trapdetect:
                        raise Trapped()
                    
                    trapdetect.add(k)

                oldmode, olddirection = mode, direction
                if next_knee is not None and next_knee.matches(current, mode, direction):
                    direction = next_knee.out_direction()
                    mode = next_knee.out_mode
                    next_knee = next_or_none(knees)
                    leg = legs.next()
                
                else: # implicit reflection/transmission
                    direction = current.propagate(p, mode, direction)
          

                if oldmode != mode or olddirection != direction:
                    if isinstance(current, Surface):
                        zz = 'surface'
                    else:
                        zz = z
                    used_phase.append(Knee(zz, olddirection, olddirection!=direction, oldmode, mode))
                    used_phase.append(Leg(direction, mode))
                
                path.append(Kink(olddirection, direction, oldmode, mode, current))

            if isinstance(current, Layer):
                if current.at_bottom(z) and direction == DOWN:
                    raise BottomReached()
                if current.at_top(z) and direction == UP:
                    raise SurfaceReached()
                direction_in = direction
                direction = current.propagate(p, mode, direction_in)

                zmin, zmax = leg.depthmin, leg.depthmax
                if zmin is not None or zmax is not None:
                    if direction_in != direction:
                        zturn = current.zturn(p, mode)
                        if zmin is not None and zturn < zmin:
                            raise MinDepthReached()
                        if zmax is not None and zturn > zmax:
                            raise MaxDepthReached()
                    else:
                        if zmin is not None and current.ztop < zmin:
                            raise MinDepthReached()
                        if zmax is not None and current.zbot > zmax:
                            raise MaxDepthReached()

                path.append(Straight(direction_in, direction, mode, current))

            if direction == DOWN:
                z = current.zbot
                if next_knee is None and self.zeq(z, zstop) and mode == mode_stop and direction == direction_stop:
                    break
                walker.down()
            else:
                z = current.ztop
                if next_knee is None and self.zeq(z, zstop) and mode == mode_stop and direction == direction_stop:
                    break
                walker.up()
                
            current = walker.current()
       
        if next_knee is not None:
            raise NotPhaseConform()
       
        used_phase.direction_stop = direction_stop
        path.set_used_phase(used_phase)

        return path

    def gather_pathes(self, phases=PhaseDef('P'), zstart=0.0, zstop=0.0, np=1000):
        '''Get all possible ray pathes for fixed source and receiver depth for one or more phase definitions.
        
        :param phases: a :py:class:`PhaseDef` object or a list of such objects
        :param zstart: source depth [m]
        :param zstop: receiver depth [m]
        :param np: controls granularity of ray path fan drafting
        :returns: a list of :py:class:`RayPath` objects
        '''

        if isinstance(phases, PhaseDef):
            phases = [ phases ]
        pathes = {}
        for phase in phases:
            mode = phase.first_leg().mode
            direction = phase.first_leg().departure
            mat = self.material(zstart, -direction)
            if mode == P:
                pmax = radius(zstart)/mat.vp
            else:
                pmax = radius(zstart)/mat.vs
            

            cached = {}
            counter = [ 0 ]
            def p_to_path(p):
                if p in cached:
                    return cached[p]

                try:
                    counter[0] += 1
                    path = self.path(p, phase, zstart, zstop)
                    if path not in pathes:
                        pathes[path] = []
                    pathes[path].append(p)

                except (BottomReached, SurfaceReached, NotPhaseConform, CannotPropagate, MaxDepthReached, MinDepthReached, Trapped), e:
                    path = None
                
                cached[p] = path
                return path
            
            def recurse(pmin, pmax, i=0):
                if i > 18:
                    return
                path1 = p_to_path(pmin)
                path2 = p_to_path(pmax)
                if path1 is None and path2 is None and i > 7:
                    return
                if path1 is None or path2 is None or hash(path1) != hash(path2):
                    recurse(pmin, (pmin+pmax)/2., i+1)
                    recurse((pmin+pmax)/2., pmax, i+1)

            recurse(0., pmax)

        for path, ps in pathes.iteritems():
            path.set_prange(min(ps), max(ps), pmax/(np-1))
        
        pathes = pathes.keys()
        pathes.sort(key=lambda x: x.pmin)
        return pathes
    
    def arrivals(self, distances=[], phases=PhaseDef('P'), zstart=0.0, zstop=0.0, np=1000, refine=True, interpolation='linear'):
        '''Compute rays and traveltimes for given distances.

        :param distances: list or array of distances [deg]
        :param phases: a :py:class:`PhaseDef` object or a list of such objects
        :param zstart: source depth [m]
        :param zstop: receiver depth [m]
        :param np: controls granularity of ray path fan drafting
        :param refine: bool flag, whether to use bisectioning to improve (p,x,t) estimated from interpolation
        :param interpolation: string key, type of interpolation to be used (``'linear'`` or ``'spline'``)
        :returns: a list of :py:class:`Ray` objects, sorted by distance
        '''
        
        distances = num.asarray(distances, dtype=num.float)
    
        arrivals = []
        for path in self.gather_pathes( phases, zstart=zstart, zstop=zstop, np=np ):
            if interpolation == 'spline':
                x2pt = path.interpolate_x2pt_spline
            elif interpolation == 'linear':
                x2pt = path.interpolate_x2pt_linear

            for x,p,t in x2pt(distances):
                arrivals.append(Ray(path, p, x, t))

        if refine:
            iref = 0
            for ray in arrivals:
                iref += ray.refine()

        arrivals.sort(key=lambda x: (x.x, x.t))
        return arrivals

    @classmethod
    def from_scanlines(cls, producer):
        '''Create layer cake model from sequence of materials at depths.
        
        :param producer: iterable yielding (depth, material, name) tuples

        Creates a new :py:class:`LayeredModel` object and uses its :py:meth:`append` method
        to add layers and discontinuities as needed.
        '''
        
        self = cls()
        for z, material, name in producer:
        
            if not self._elements:
                self.append(Surface(0.0, material))
                if not self.zeq(z, 0.0):
                    self.append(HomogeneousLayer(0.0, depth, material, name=name))
            else:
                element = self._elements[-1]
                if self.zeq(element.zbot, z):
                    assert isinstance(element, Layer)
                    self.append(Interface(z, element.mbot, material, name=name))

                else:
                    if isinstance(element, Discontinuity):
                        ztop = element.z
                        mtop = element.mbelow
                    elif isinstance(element, Layer):
                        ztop = element.zbot
                        mtop = element.mbot
                    
                    if mtop == material:
                        layer = HomogeneousLayer(ztop, z, material, name=name)
                    else:
                        layer = GradientLayer(ztop, z, mtop, material, name=name)
                    
                    self.append(layer)
    
        return self

    def iter_material_parameter(self, get):
        assert get in ('vp', 'vs', 'rho', 'qp', 'qs')
        getter = operator.attrgetter(get)
        for layer in self.layers():
            yield getter(layer.mtop)
            yield getter(layer.mbot)
         
    def min(self, get='vp'):
        '''Find minimum value of a material property defined in the model.

        :param get: property to be querried (```'vp'``, ``'vs'``, ``'rho'``, ``'qp'``, or ``'qs'``)
        '''

        return min(self.iter_material_parameter(get))

    def max(self, get='vp'):
        '''Find maximum value of a material property defined in the model.
        
        :param get: property to be querried (```'vp'``, ``'vs'``, ``'rho'``, ``'qp'``, or ``'qs'``)
        '''

        return max(self.iter_material_parameter(get))

    def __str__(self):
        return '\n'.join( str(element) for element in self._elements )
                
def read_hyposat_model(fn):
    '''Reader for HYPOSAT earth model files.

    To be used as producer in :py:meth:`LayeredModel.from_scanlines`.
    '''

    f = open(fn, 'r')
    translate = { 'MOHO': 'moho', 'CONR': 'conrad' }
    lname = None
    for iline, line in enumerate(f):
        if iline == 0:
            continue

        z, vp, vs, name = util.unpack_fixed('f10,f10,f10,a4', line)
        if not name:
            name = None
        material = Material(vp*1000., vs*1000.)

        tname = translate.get(lname, lname)
        yield z*1000., material, tname

        lname = name

    f.close()
        
def read_nd_model(fn):
    '''Reader for TauP style '.nd' (named discontinuity) files.

    To be used as producer in :py:meth:`LayeredModel.from_scanlines`.
    '''
    f = open(fn, 'r')
    translate = { 'mantle': 'moho', 'outer-core': 'cmb', 'inner-core': 'icb' }
    name = None
    for line in f:
        toks = line.split()
        if len(toks) == 6:
            z, vp, vs, rho, qp, qs = [ float(x) for x in toks ]
            material = Material(vp*1000., vs*1000., rho*1000., qp, qs)
            yield z*1000., material, name
            name = None
        elif len(toks) == 1:
            name = translate[toks[0]]

    f.close()

def load_model(fn, format='nd'):
    '''Load layered earth model from file.
    
    :param fn: filename
    :param format: format 
    :returns: object of type :py:class:`LayeredModel`

    The following formats are currently supported:

    ============== ===========================================================================
    format         description
    ============== ===========================================================================
    ``'nd'``       'named discontinuity' format used by the TauP programs  
    ``'hyposat'``  format used by the HYPOSAT location program
    ============== ===========================================================================
    '''

    if format == 'nd':
        reader = read_nd_model(fn)
    elif format == 'hyposat':
        reader = read_hyposat_model(fn)
    else:
        assert False, 'unsupported model format'

    return LayeredModel.from_scanlines(reader)

def castagna_vs_to_vp(vs):
    '''Calculate vp from vs using castagna's relation.

    Castagna's relation (the mudrock line) is an empirical relation for vp/vs for 
    siliciclastic rocks (i.e. sandstones and shales). [Castagna et al., 1985]

        vp = 1.16 * vs + 1360 [m/s]

    :param vs: S-wave velocity [m/s]
    :returns: vp in [m/s]
    '''

    return vs*1.16 + 1360.0

def evenize(x,y, minsize=10):
    if x.size < minsize:
        return x
    ry = (y.max()-y.min())
    if ry == 0:
        return x
    dx = (x[1:] - x[:-1])/(x.max()-x.min())
    dy = (y[1:] + y[:-1])/ry
    
    s = num.zeros(x.size) 
    s[1:] = num.cumsum(num.sqrt(dy**2 + dx**2))
    s2 = num.linspace(0,s[-1],x.size)
    x2 = num.interp(s2, s, x)
    x2[0] = x[0]
    x2[-1] = x[-1]
    return x2

def filled(v, *args, **kwargs):
    '''Create NumPy array filled with given value.

    This works like :py:func:`numpy.ones` but initializes the array with `v` instead
    of ones.
    '''
    x = num.empty(*args, **kwargs)
    x.fill(v)
    return x

def next_or_none(i):
    try:
        return i.next()
    except StopIteration:
        return None

def reci_or_none(x):
    try:
        return 1./x
    except ZeroDivisionError:
        return None

def monotony(x):
    '''Check if an array is strictly increasing or decreasing.
    
    Given an array `x`, returns `1` if the values of x are in strictly
    increasing order and `-1` if they are in strictly decreasing order, or zero
    otherwise.
    '''
    n = x.size
    p = num.sum(num.sign(x))
    if n == p:
        return 1
    if n == -p:
        return -1
    else:
        return 0

def xytups(xx,yy):
    d = []
    for x,y in zip(xx,yy):
        if num.isfinite(y):
            d.append((x,y))
    return d

def interp(x, xp, fp, monoton):
    if monoton==1:
        return xytups(x, num.interp(x, xp, fp, left=num.nan, right=num.nan))
    elif monoton==-1:
        return xytups(x, num.interp(x, xp[::-1], fp[::-1], left=num.nan, right=num.nan))
    else:
        fs = []
        for xv in x:
            indices = num.where(num.logical_and(xp[:-1] <= xv , xv < xp[1:]))[0]
            fvs = []
            for i in indices:
                xr = (xv - xp[i])/(xp[i+1]-xp[i])
                fv = xr*fp[i] + (1.-xr)*fp[i+1]
                fs.append((xv,fv))
                
        return fs

def float_or_none(x):
    if x is not None:
        return float(x)

def parstore_float(thelocals, obj, *args):
    for k,v in thelocals.iteritems():
        if k != 'self' and (not args or k in args):
            setattr(obj, k, float_or_none(v))

