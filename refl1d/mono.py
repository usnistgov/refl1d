"""
.. sidebar:: On this Page

        * :class:`Free form <refl1d.freeform.Freeform>`
"""


from __future__ import division, with_statement
from numpy import (diff, hstack, sqrt, searchsorted, asarray, cumsum,
                   inf, nonzero, linspace)
from mystic.parameter import Parameter as Par, Function as ParFunction
from . import numpyerrors
from .model import Layer

#TODO: add left_sld,right_sld to all layers so that fresnel works
#TODO: access left_sld,right_sld so freeform doesn't need left,right
#TODO: restructure to use vector parameters
#TODO: allow the number of layers to be adjusted by the fit
class FreeLayer(Layer):
    """
    A freeform section of the sample modeled with splines.

    sld (rho) and imaginary sld (irho) can be modeled with a separate
    number of control points. The control points can be equally spaced
    in the layers unless rhoz or irhoz are specified. If the z values
    are given, they must be in the range [0,1].  One control point is
    anchored at either end, so there are two fewer z values than controls
    if z values are given.

    Layers have a slope of zero at the ends, so the automatically blend
    with slabs.
    """
    def __init__(self, thickness=0, left=None, right=None,
                 rho=[], irho=[], rhoz=[], irhoz=[], name="Freeform"):
        self.name = name
        self.left, self.right = left,right
        self.thickness = Par.default(thickness, limits=(0,inf),
                                   name=name+" thickness")
        self.rho,self.irho,self.rhoz,self.irhoz \
            = [[Par.default(p,name=name+" [%d] %s"%(i,part),limits=limits)
                for i,p in enumerate(v)]
               for v,part,limits in zip((rho, irho, rhoz, irhoz),
                                        ('rho', 'irho', 'rhoz', 'irhoz'),
                                        ((-inf,inf),(-inf,inf),(0,1),(0,1))
                                        )]
        if len(self.rhoz) > 0 and len(self.rhoz) != len(self.rho):
            raise ValueError("must have one z value for each rho")
        if len(self.irhoz) > 0 and len(self.irhoz) != len(self.irho):
            raise ValueError("must have one z value for each irho")
    def parameters(self):
        return dict(rho=self.rho,
                    rhoz=self.rhoz,
                    irho=self.irho,
                    irhoz=self.irhoz,
                    left=self.left.parameters(),
                    right=self.right.parameters(),
                    thickness=self.thickness)
    def render(self, probe, slabs):
        thickness = self.thickness.value
        left_rho,left_irho = self.left.sld(probe)
        right_rho,right_irho = self.right.sld(probe)
        Pw,Pz = slabs.microslabs(thickness)
        
        rho = hstack((left_rho, [p.value for p in self.rho], right_rho))
        rhoz = hstack((0, [p.value for p in self.rhoz], 1))
        Prho = monospline(rho, rhoz, Pz)
        
        irho = hstack((left_irho, [p.value for p in self.irho], right_irho))
        irhoz = hstack((0, [p.value for p in self.irhoz], 1))
        Pirho = monospline(irho, irhoz, Pz)

        slabs.extend(rho=[Prho], irho=[Pirho], w=Pw)

class FreeInterfaceW(Layer):
    """
    A freeform section of the sample modeled with monotonic splines.

    Layers have a slope of zero at the ends, so the automatically blend
    with slabs.
    """
    def __init__(self, interface=0,
                 below=None, above=None,
                 dz=None, dp=None, name="Interface"):
        self.name = name
        self.below, self.above = below,above
        self.interface = Par.default(interface, limits=(0,inf),
                                     name=name+" interface")
        
        # Choose reasonable defaults if not given
        if dp is None and dz is None:
            dp = [1]*5
        if dp is None:
            dp = [1]*len(dz)
        if dz is None:
            dz = [10./len(dp)]*len(dp)
        if len(dz) != len(dp):
            raise ValueError("Need one dz for every dp")
        #if len(z) != len(vf)+2:
        #    raise ValueError("Only need vf for interior z, so len(z)=len(vf)+2")
        self.dz = [Par.default(p,name=name+" dz[%d]"%i,limits=(0,inf))
                  for i,p in enumerate(dz)]
        self.dp = [Par.default(p,name=name+" dp[%d]"%i,limits=(0,inf))
                   for i,p in enumerate(dp)]
    def _get_thickness(self):
        w = sum(v.value for v in self.dz)
        return Par(w,name=self.name+" thickness")
    def _set_thickness(self, v):
        if v != 0: 
            raise ValueError("thickness cannot be set for FreeformInterface")
    thickness = property(_get_thickness, _set_thickness)
        
    def parameters(self):
        return dict(dz=self.dz,
                    dp=self.dp,
                    below=self.below.parameters(),
                    above=self.above.parameters(),
                    interface=self.interface)
    def render(self, probe, slabs):
        interface = self.interface.value
        left_rho,left_irho = self.below.sld(probe)
        right_rho,right_irho = self.above.sld(probe)
        z = hstack( (0, cumsum([v.value for v in self.dz])) )
        p = hstack( (0, cumsum([v.value for v in self.dp])) )
        thickness = z[-1]
        if p[-1] == 0: p[-1] = 1
        p /= p[-1]
        Pw,Pz = slabs.microslabs(z[-1])
        profile = monospline(z, p, Pz)
        lidx,ridx = searchsorted(profile,[0.01,0.99])
        ridx = min( (ridx, len(profile)-1) )
        Prho  = (1-profile)*left_rho  + profile*right_rho
        Pirho = (1-profile)*left_irho + profile*right_irho
        slabs.extend(rho=[left_rho], irho=[left_irho], w=[Pz[lidx]])
        slabs.extend(rho=[Prho[lidx:ridx]], 
                     irho=[Pirho[lidx:ridx]], 
                     w=Pw[lidx:ridx])
        slabs.extend(rho=[right_rho],irho=[right_irho],
                     sigma=[interface],
                     w=[thickness-Pz[ridx]])

def inflections(dx,dy):
    x = hstack( (0, cumsum(dx)) )
    y = hstack( (0, cumsum(dy)) )
    return count_inflections(x,y)


class FreeInterface(Layer):
    """
    A freeform section of the sample modeled with monotonic splines.

    Layers have a slope of zero at the ends, so the automatically blend
    with slabs.
    """
    def __init__(self, thickness=0, interface=0,
                 below=None, above=None,
                 dz=None, dp=None, name="Interface"):
        self.name = name
        self.below, self.above = below,above
        self.thickness = Par.default(thickness, limits=(0,inf),
                                     name=name+" thickness")
        self.interface = Par.default(interface, limits=(0,inf),
                                     name=name+" interface")
        
        
        # Choose reasonable defaults if not given
        if dp is None and dz is None:
            dp = [1]*5
        if dp is None:
            dp = [1]*len(dz)
        if dz is None:
            dz = [1]*len(dp)
        if len(dz) != len(dp):
            raise ValueError("Need one dz for every dp")

        #if len(z) != len(vf)+2:
        #    raise ValueError("Only need vf for interior z, so len(z)=len(vf)+2")
        self.dz = [Par.default(p,name=name+" dz[%d]"%i,limits=(0,inf))
                  for i,p in enumerate(dz)]
        self.dp = [Par.default(p,name=name+" dp[%d]"%i,limits=(0,inf))
                   for i,p in enumerate(dp)]
        self.inflections = ParFunction(inflections, dx=self.dz, dy=self.dp,
                                       name=name+" inflections")

    def parameters(self):
        return dict(dz=self.dz,
                    dp=self.dp,
                    below=self.below.parameters(),
                    above=self.above.parameters(),
                    thickness=self.thickness,
                    interface=self.interface,
                    inflections=self.inflections)
    def render(self, probe, slabs):
        thickness = self.thickness.value
        interface = self.interface.value
        left_rho,left_irho = self.below.sld(probe)
        right_rho,right_irho = self.above.sld(probe)
        z = hstack( (0, cumsum([v.value for v in self.dz])) )
        p = hstack( (0, cumsum([v.value for v in self.dp])) )
        if p[-1] == 0: p[-1] = 1
        p *= 1/p[-1]
        z *= thickness/z[-1]
        Pw,Pz = slabs.microslabs(thickness)
        profile = monospline(z, p, Pz)
        lidx,ridx = searchsorted(profile,[0.01,0.99])
        ridx = min( (ridx, len(profile)-1) )
        Prho  = (1-profile)*left_rho  + profile*right_rho
        Pirho = (1-profile)*left_irho + profile*right_irho
        slabs.extend(rho=[left_rho], irho=[left_irho], w=[Pz[lidx]])
        slabs.extend(rho=[Prho[lidx:ridx]], 
                     irho=[Pirho[lidx:ridx]], 
                     w=Pw[lidx:ridx])
        slabs.extend(rho=[right_rho],irho=[right_irho],
                     sigma=[interface],
                     w=[thickness-Pz[ridx]])

@numpyerrors.ignored
def count_inflections(x,y):
    """
    Count the number of inflection points in the spline curve
    """
    m = (y[2:]-y[:-2])/(x[2:]-x[:-2])
    b = y[2:] - m*x[2:]
    delta = y[1:-1] - (m*x[1:-1] + b)
    delta = delta[nonzero(delta)] # ignore points on the line
    sign_change = (delta[1:]*delta[:-1]) < 0
    return sum(sign_change)

def plot_inflection(x,y):
    m = (y[2:]-y[:-2])/(x[2:]-x[:-2])
    b = y[2:] - m*x[2:]
    delta = y[1:-1] - (m*x[1:-1] + b)
    t = linspace(x[0],x[-1],400)
    import pylab
    ax1=pylab.subplot(211)
    pylab.plot(t,monospline(x,y,t),'-b',x,y,'ob')
    pylab.subplot(212, sharex=ax1)
    delta_x = x[1:-1]
    pylab.stem(delta_x,delta)
    pylab.plot(delta_x[delta<0],delta[delta<0],'og')
    pylab.axis([x[0],x[-1],min(min(delta),0),max(max(delta),0)])
    

@numpyerrors.ignored
def monospline(x, y, xt):
    r"""
    Monotonic cubic hermite interpolation.
    
    Returns $p(x_t)$ where $p(x_i)= y_i$ and $p(x) \leq p(xi)$ 
    if $y_i \leq y_{i+1}$ for all $y_i$.  Also works for decreasing
    values $y$, resulting in decreasing $p(x)$.  If $y$ is not monotonic,
    then $p(x)$ may peak higher than any $y$, so this function is not
    suitable for a strict constraint on the interpolated function when
    $y$ values are unconstrained.
    
    http://en.wikipedia.org/wiki/Monotone_cubic_interpolation
    """
    x = hstack((x[0]-1,x,x[-1]+1))
    y = hstack((y[0], y, y[-1]))
    dx = diff(x)
    dy = diff(y)
    delta = dy/dx
    m = (delta[1:]+delta[:-1])/2
    m = hstack( (0, m, 0) )
    alpha, beta = m[:-1]/delta, m[1:]/delta
    d = alpha**2+beta**2

    for i in range(len(m)-1):
        if dy[i] == 0 or alpha[i] == 0 or beta[i] == 0:
            m[i] = m[i+1] = 0
        elif d[i] > 9:
            tau = 3/sqrt(d[i])
            m[i] = tau*alpha[i]*delta[i]
            m[i+1] = tau*beta[i]*delta[i]
    #m[ dy[1:]*dy[:-1]<0 ] = 0

    return hermite(x,y,m,xt)


@numpyerrors.ignored
def hermite(x,y,m,xt):
    """
    Computes the cubic hermite polynomial p(xt).
    
    The polynomial goes through all points (x_i,y_i) with slope
    m_i at the point.
    """
    x,y,m,xt = [asarray(v,'d') for v in x,y,m,xt]
    idx = searchsorted(x[1:-1],xt)
    h = x[idx+1] - x[idx]
    h[h<=1e-10]=1e-10
    s = (y[idx+1] - y[idx])/h
    v = xt-x[idx]
    c3,c2,c1,c0 = ((m[idx]+m[idx+1]-2*s)/h**2,
                   (3*s-2*m[idx]-m[idx+1])/h,
                   m[idx],
                   y[idx])
    return ((c3*v + c2)*v + c1)*v + c0