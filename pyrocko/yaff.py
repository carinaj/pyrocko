'''File IO module for SICK traces format.'''

from pyrocko.file import File, numtype2type, NoDataAvailable
import trace
from util import ensuredirs

record_formats = {

    'trace': {
            'network': 'string',
            'station': 'string',
            'location': 'string',
            'channel': 'string',
            'tmin': 'time_string',
            'tmax': 'time_string',
            'deltat': 'f8',
            'ydata': ('@i2', '@i4', '@i8', '@i2', '@i4', '@i8',  '@f4', '@f8'),
    },
}

def extract(tr, format):
    d = {}
    for k in format.keys():
        d[k] = getattr(tr,k)
    return d

class TracesFileIO(File):
    
    def __init__(self, file):
        File.__init__(self, file, type_label='YAFF', version='0000', record_formats=record_formats)
        
    def get_type(self, key, value):
        return numtype2type[value.dtype.type]
        
    def from_dict(self, d):
        return trace.Trace(**d)
    
    def to_dict(self, tr):
        return extract(tr, record_formats['trace'])
    
    def load(self, load_data=True):
        while True: 
            try:
                r = None
                r = self.next_record()
                
                if r.type == 'trace':
                    exclude = None
                    if not load_data:
                        exclude = ('ydata',)
                        
                    d = r.unpack(exclude=exclude)
                    tr = self.from_dict(d)
                    yield tr
                    
            except NoDataAvailable:
                break
            
    def save(self, traces):
        for tr in traces:
            r = self.add_record('trace', make_hash=True)
            r.pack(self.to_dict(tr))
            r.close()

def load(fn, load_data=True):
    f = open(fn, 'r')
    tf = TracesFileIO(f)
    for tr in tf.load(load_data=load_data):
        yield tr
    tf.close()
    f.close()
    
def save(traces, filename_template, additional={}, max_open_files=10):
    fns = set()
    open_files = {}
    
    def close_files():
        while open_files:
            open_files.popitem()[1].close()
            
    for tr in traces:
        fn = tr.fill_template(filename_template, **additional)
        
        if fn not in open_files:
            if len(open_files) >= max_open_files:
                close_files()
                
            if fn not in fns: 
                ensuredirs(fn)
            
            open_files[fn] = open(fn, 'wa'[fn in fns])            
            fns.add(fn)
        
        tf = TracesFileIO(open_files[fn])
        tf.save([tr])
        tf.close()
        
    close_files()
            
    return list(fns)
