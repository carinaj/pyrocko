'''Snuffling infrastructure

This module provides the base class :py:class:`Snuffling` for user-defined snufflings and 
some utilities for their handling.
'''


import os, sys, logging, traceback, tempfile

from PyQt4.QtCore import *
from PyQt4.QtGui import *

import pile

from gui_util import ValControl, LinValControl

logger = logging.getLogger('pyrocko.snufflings')

def _str_traceback():
    return '%s' % (traceback.format_exc(sys.exc_info()[2]))

class Param:
    '''Definition of an adjustable parameter for the snuffling. The snuffling
    may display controls for user input for such parameters.'''
    
    def __init__(self, name, ident, default, minimum, maximum, low_is_none=None, high_is_none=None):
        self.name = name
        self.ident = ident
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.low_is_none = low_is_none
        self.high_is_none = high_is_none

class Switch:
    '''Definition of a switch for the snuffling. The snuffling may display a
    checkbox for such a switch.'''

    def __init__(self, name, ident, default):
        self.name = name
        self.ident = ident
        self.default = default

class Choice:
    '''Definition of a choice for the snuffling. The snuffling may display a
    menu for such a choice.'''

    def __init__(self, name, ident, default, choices):
        self.name = name
        self.ident = ident
        self.default = default
        self.choices = choices

class Snuffling:
    '''Base class for user snufflings.
    
    Snufflings are plugins for snuffler (and other applications using the
    :py:class:`pyrocko.pile_viewer.PileOverview` class defined in
    ``pile_viewer.py``). They can be added, removed and reloaded at runtime and
    should provide a simple way of extending the functionality of snuffler.
    
    A snuffling has access to all data available in a pile viewer, can process 
    this data and can create and add new traces and markers to the viewer.
    '''

    def __init__(self):
        self._path = None

        self._name = 'Untitled Snuffling'
        self._viewer = None
        self._tickets = []
        self._markers = []
        
        self._delete_panel = None
        self._delete_menuitem = None
        
        self._panel_parent = None
        self._menu_parent = None
        
        self._panel = None
        self._menuitem = None
        self._parameters = []
        self._param_controls = {}
        
        self._live_update = True
        self._previous_output_filename = None
        self._previous_input_filename = None

        self._tempdir = None
        
    def setup(self):
        '''Setup the snuffling.
        
        This method should be implemented in subclass and contain e.g. calls to 
        :py:meth:`set_name` and :py:meth:`add_parameter`.
        '''
        
        pass
    
    def init_gui(self, viewer, panel_parent, menu_parent, reloaded=False):
        '''Set parent viewer and hooks to add panel and menu entry.
        
        This method is called from the
        :py:class:`pyrocko.pile_viewer.PileOverview` object. Calls
        :py:meth:`setup_gui`.  '''
        
        self._viewer = viewer
        self._panel_parent = panel_parent
        self._menu_parent = menu_parent
        
        self.setup_gui(reloaded=reloaded)
        
    def setup_gui(self, reloaded=False):
        '''Create and add gui elements to the viewer.
        
        This method is initially called from :py:meth:`init_gui`. It is also called,
        e.g. when new parameters have been added or if the name of the snuffling 
        has been changed.
        '''
        
        if self._panel_parent is not None:
            self._panel = self.make_panel(self._panel_parent)
            if self._panel:
                self._panel_parent.add_panel(self.get_name(), self._panel, reloaded)
       
        if self._menu_parent is not None:
            self._menuitem = self.make_menuitem(self._menu_parent)
            if self._menuitem:
                self._menu_parent.add_snuffling_menuitem(self._menuitem)
        
    def delete_gui(self):
        '''Remove the gui elements of the snuffling.
        
        This removes the panel and menu entry of the widget from the viewer and
        also removes all traces and markers added with the :py:meth:`add_traces` 
        and :py:meth:`add_markers` methods.
        '''
        
        self.cleanup()
        
        if self._panel is not None:
            self._panel_parent.remove_panel(self._panel)
            self._panel = None
            
        if self._menuitem is not None:
            self._menu_parent.remove_snuffling_menuitem(self._menuitem)
            self._menuitem = None
            
    def set_name(self, name):
        '''Set the snuffling's name.
        
        The snuffling's name is shown as a menu entry and in the panel header.
        '''
        
        self._name = name
        
        if self._panel or self._menuitem:
            self.delete_gui()
            self.setup_gui()
    
    def get_name(self):
        '''Get the snuffling's name.'''
        
        return self._name
    
    def error(self, reason):
        box = QMessageBox(self.get_viewer())
        box.setText(reason)
        box.exec_()
    
    def fail(self, reason):
        self.error(reason)
        raise SnufflingCallFailed(reason) 
   
    def tempdir(self):
        if self._tempdir is None:
            self._tempdir = tempfile.mkdtemp('', 'snuffling-tmp-')
        
        return self._tempdir

    def set_live_update(self, live_update):
        '''Enable/disable live updating.
        
        When live updates are enabled, the :py:meth:`call` method is called whenever
        the user changes a parameter. If it is disabled, the user has to 
        initiate such a call manually by triggering the snuffling's menu item
        or pressing the call button.
        '''
        self._live_update = live_update
    
    def add_parameter(self, param):
        '''Add an adjustable parameter to the snuffling.
        
        :param param: object of type :py:class:`Param`
        
        For each parameter added, controls are added to the snuffling's panel,
        so that the parameter can be adjusted from the gui.
        '''
        
        self._parameters.append(param)
        self.set_parameter(param.ident, param.default)
        
        if self._panel is not None:
            self.delete_gui()
            self.setup_gui()
    
    def get_parameters(self):
        '''Get the snufflings adjustable parameter definitions.
        
        
        Returns a list of objects of type Param.
        '''
        
        return self._parameters
    
    def set_parameter(self, ident, value):
        '''Set one of the snuffling's adjustable parameters.
        
        :param ident: identifier of the parameter
        :param value: new value of the parameter
            
        This is usually called when the parameter has been set via the gui 
        controls.
        '''
        
        setattr(self, ident, value)
        
    def get_parameter(self, ident):
        return getattr(self, ident)

    def get_settings(self):
        params = self.get_parameters()
        settings = {}
        for param in params:
            settings[param.ident] = self.get_parameter(param.ident)

        return settings

    def set_settings(self, settings):
        params = self.get_parameters()
        dparams = dict( [ (param.ident, param) for param in params ] )
        for k,v in settings.iteritems():
            if k in dparams:
                self.set_parameter(k,v)
                if k in self._param_controls:
                    control = self._param_controls[k]
                    control.set_value(v)

    def get_viewer(self):
        '''Get the parent viewer.
        
        Returns a reference to an object of type :py:class:`PileOverview`, which is the
        main viewer widget.
        
        If no gui has been initialized for the snuffling, a :py:exc:`NoViewerSet` 
        exception is raised.
        '''
        
        if self._viewer is None:
            raise NoViewerSet()
        return self._viewer
    
    def get_pile(self):
        '''Get the pile.
        
        If a gui has been initialized, a reference to the viewer's internal pile
        is returned. If not, the :py:meth:`make_pile` method (which may be overloaded in
        subclass) is called to create a pile. This can be utilized to make 
        hybrid snufflings, which may work also in a standalone mode.
        '''
        
        try:
            p =self.get_viewer().get_pile()
        except NoViewerSet:
            p = self.make_pile()
            
        return p
        
    def chopper_selected_traces(self, fallback=False, marker_selector=None, *args, **kwargs ):
        '''Iterate over selected traces.
        
        This is a shortcut to get all trace data contained in the selected 
        markers in the running snuffler. For each selected marker, 
        :py:meth:`pyrocko.pile.Pile.chopper` is called with the arguments *tmin*, *tmax*, and 
        *trace_selector* set to values according to the marker. Additional
        arguments to the chopper are handed over from *\*args* and *\*\*kwargs*.
        
        :param fallback: if ``True``, if no selection has been marked, use the content
               currently visible in the viewer.
        :param marker_selector: if not ``None`` a callback to filter markers.
               
        '''
        
        viewer = self.get_viewer()
        markers = viewer.selected_markers()
        if marker_selector is not None:
            markers = [  marker for marker in markers if marker_selector(marker) ] 
        pile = self.get_pile()
        
        if markers:
            
            for marker in markers:
                if not marker.nslc_ids:
                    trace_selector = None
                else:
                    trace_selector = lambda tr: tr.nslc_id in marker.nslc_ids
                
                for traces in pile.chopper(
                        tmin = marker.tmin,
                        tmax = marker.tmax,
                        trace_selector = trace_selector,
                        *args,
                        **kwargs):
                    
                    yield traces
                    
        elif fallback:
            
            tmin, tmax = viewer.get_time_range()
            for traces in pile.chopper(
                    tmin = tmin,
                    tmax = tmax,
                    *args,
                    **kwargs):
                
                yield traces
        else:
            raise NoTracesSelected()
                    
    def get_selected_time_range(self, fallback=False):
        '''Get the time range spanning all selected markers.'''
        
        viewer = self.get_viewer()
        markers = viewer.selected_markers()
        mins = [ marker.tmin for marker in markers ]
        maxs = [ marker.tmax for marker in markers ]
        
        if mins and maxs:
            tmin = min(mins)
            tmax = max(maxs)
            
        elif fallback:
            tmin, tmax  = viewer.get_time_range()
            
        else:
            raise NoTracesSelected()
            
        return tmin, tmax

    def make_pile(self):
        '''Create a pile.
        
        To be overloaded in subclass. The default implementation just calls
        :py:func:`pyrocko.pile.make_pile` to create a pile from command line arguments.
        '''
        
        cachedirname = '/tmp/snuffle_cache_%s' % os.environ['USER']
        return pile.make_pile(cachedirname=cachedirname)
        
    def make_panel(self, parent):
        '''Create a widget for the snuffling's control panel.
        
        Normally called from the :py:meth:`setup_gui` method. Returns ``None`` if no panel
        is needed (e.g. if the snuffling has no adjustable parameters).'''
    
        params = self.get_parameters()
        self._param_controls = {}
        if params:
            sarea = MyScrollArea(parent.get_panel_parent_widget())
            frame = QFrame(sarea)
            sarea.setWidget(frame)
            sarea.setWidgetResizable(True)
            layout = QGridLayout()
            frame.setLayout( layout )
            
            irow = 0
            have_switches = False
            for iparam, param in enumerate(params):
                if isinstance(param, Param):
                    if param.minimum <= 0.0:
                        param_widget = LinValControl(high_is_none=param.high_is_none, low_is_none=param.low_is_none)
                    else:
                        param_widget = ValControl(high_is_none=param.high_is_none, low_is_none=param.low_is_none)
                    param_widget.setup(param.name, param.minimum, param.maximum, param.default, iparam)
                    self.get_viewer().connect( param_widget, SIGNAL("valchange(PyQt_PyObject,int)"), self.modified_snuffling_panel )

                    self._param_controls[param.ident] = param_widget
                    layout.addWidget( param_widget, irow, 0, 1, 3 )
                    irow += 1
                elif isinstance(param, Choice):
                    param_widget = ChoiceControl(param.ident, param.default, param.choices, param.name)
                    self.get_viewer().connect( param_widget, SIGNAL('choosen(PyQt_PyObject,PyQt_PyObject)'), self.choose_on_snuffling_panel )
                    self._param_controls[param.ident] = param_widget
                    layout.addWidget( param_widget, irow, 0, 1, 3 )
                    irow += 1
                elif isinstance(param, Switch):
                    have_switches = True

            if have_switches:

                swframe = QFrame(sarea)
                swlayout = QGridLayout()
                swframe.setLayout( swlayout )
                isw = 0
                for iparam, param in enumerate(params):
                    if isinstance(param, Switch):
                        param_widget = SwitchControl(param.ident, param.default, param.name)
                        self.get_viewer().connect( param_widget, SIGNAL('sw_toggled(PyQt_PyObject,bool)'), self.switch_on_snuffling_panel )
                        self._param_controls[param.ident] = param_widget
                        swlayout.addWidget( param_widget, isw/10, isw%10 )
                        isw += 1
                
                layout.addWidget( swframe, irow, 0, 1, 3 )
                irow += 1

            live_update_checkbox = QCheckBox('Auto-Run')
            if self._live_update:
                live_update_checkbox.setCheckState(Qt.Checked)
            layout.addWidget( live_update_checkbox, irow, 0 )
            self.get_viewer().connect( live_update_checkbox, SIGNAL("toggled(bool)"), self.live_update_toggled )
        
            clear_button = QPushButton('Clear')
            layout.addWidget( clear_button, irow, 1 )
            self.get_viewer().connect( clear_button, SIGNAL("clicked()"), self.clear_button_triggered )
        
            call_button = QPushButton('Run')
            layout.addWidget( call_button, irow, 2 )
            self.get_viewer().connect( call_button, SIGNAL("clicked()"), self.call_button_triggered )

            return sarea 
            
        else:
            return None
    
    def make_menuitem(self, parent):
        '''Create the menu item for the snuffling.
        
        This method may be overloaded in subclass and return ``None``, if no menu 
        entry is wanted.
        '''
        
        item = QAction(self.get_name(), None)
        self.get_viewer().connect( item, SIGNAL("triggered(bool)"), self.menuitem_triggered )
        return item
    
    def output_filename(self, caption='Save File', dir='', filter='', selected_filter=None):
        
        '''Query user for an output filename.
        
        This is currently just a wrapper to :py:func:`QFileDialog.getSaveFileName`.
        A :py:exc:`UserCancelled` exception is raised if the user cancels the dialog.
        '''
        
        if not dir and self._previous_output_filename:
            dir = self._previous_output_filename
            
        fn = QFileDialog.getSaveFileName(
            self.get_viewer(),
            caption,
            dir,
            filter,
            selected_filter)
            
        if not fn:
            raise UserCancelled()
        
        self._previous_output_filename = fn
        return str(fn)
    
    def input_filename(self, caption='Open File', dir='', filter='', selected_filter=None):
        
        '''Query user for an input filename.
        
        This is currently just a wrapper to :py:func:`QFileDialog.getOpenFileName`.
        A :py:exc:`UserCancelled` exception is raised if the user cancels the dialog.
        '''
        
        if not dir and self._previous_input_filename:
            dir = self._previous_input_filename
            
        fn = QFileDialog.getOpenFileName(
            self.get_viewer(),
            caption,
            dir,
            filter,
            selected_filter)
            
        if not fn:
            raise UserCancelled()
        
        self._previous_input_filename = fn
        return str(fn)
    
    def modified_snuffling_panel(self, value, iparam):
        '''Called when the user has played with an adjustable parameter.
        
        The default implementation sets the parameter, calls the snuffling's 
        :py:meth:`call` method and finally triggers an update on the viewer widget.
        '''
        
        param = self.get_parameters()[iparam]
        self.set_parameter(param.ident, value)
        if self._live_update:
            self.check_call()
            self.get_viewer().update()
        

    def switch_on_snuffling_panel(self, ident, state):
        '''Called when the user has toggled a switchable parameter.'''

        self.set_parameter(ident, state)
        if self._live_update:
            self.check_call()
            self.get_viewer().update()

    def choose_on_snuffling_panel(self, ident, state):
        '''Called when the user has made a choice about a choosable parameter.'''

        self.set_parameter(ident, state)
        if self._live_update:
            self.check_call()
            self.get_viewer().update()

    def menuitem_triggered(self, arg):
        '''Called when the user has triggered the snuffling's menu.
        
        The default implementation calls the snuffling's :py:meth:`call` method and triggers
        an update on the viewer widget.'''
        self.check_call()
        self.get_viewer().update()
        
    def call_button_triggered(self):
        '''Called when the user has clicked the snuffling's call button.
        
        The default implementation calls the snuffling's :py:meth:`call` method and triggers
        an update on the viewer widget.'''
        self.check_call()
        self.get_viewer().update()
        
    def clear_button_triggered(self):
        '''Called when the user has clicked the snuffling's clear button.
        
        This calls the :py:meth:`cleanup` method and triggers an update on the viewer 
        widget.'''
        self.cleanup()
        self.get_viewer().update()
        
    def live_update_toggled(self, on):
        '''Called when the checkbox for live-updates has been toggled.'''
        
        self.set_live_update(on)
        
    def add_traces(self, traces):
        '''Add traces to the viewer.
        
        :param traces: list of objects of type :py:class:`pyrocko.trace.Trace`
            
        The traces are put into a :py:class:`pyrocko.pile.MemTracesFile` and added to the viewer's 
        internal pile for display. Note, that unlike with the traces from the 
        files given on the command line, these traces are kept in memory and so
        may quickly occupy a lot of ram if a lot of traces are added.
        
        This method should be preferred over modifying the viewer's internal 
        pile directly, because this way, the snuffling has a chance to
        automatically remove its private traces again (see :py:meth:`cleanup` method).
        '''
        
        ticket = self.get_viewer().add_traces(traces)
        self._tickets.append( ticket )
        return ticket

    def add_trace(self, tr):
        self.add_traces([tr])

    def add_markers(self, markers):
        '''Add some markers to the display.
        
        Takes a list of objects of type :py:class:`pyrocko.pile_viewer.Marker` and adds
        these to the viewer.
        '''
        
        self.get_viewer().add_markers(markers)
        self._markers.extend(markers)

    def add_marker(self, marker):
        self.add_markers([marker])

    def cleanup(self):
        '''Remove all traces and markers which have been added so far by the snuffling.'''
        
        try:
            viewer = self.get_viewer()
            viewer.release_data(self._tickets)
            viewer.remove_markers(self._markers)
            
        except NoViewerSet:
            pass
        
        self._tickets = []
        self._markers = []
   
    def check_call(self):
        try:
            self.call()
        except SnufflingCallFailed, e:
            logger.error('%s: %s' % (self._name, str(e)))

    def call(self):
        '''Main work routine of the snuffling.
        
        This method is called when the snuffling's menu item has been triggered
        or when the user has played with the panel controls. To be overloaded in
        subclass. The default implementation does nothing useful.
        '''
        
        pass
    
    def __del__(self):
        self.cleanup()
        if self._tempdir is not None:
            import shutil
            shutil.rmtree(self._tempdir)

class NoViewerSet(Exception):
    '''This exception is raised, when no viewer has been set on a Snuffling.'''
    pass

class NoTracesSelected(Exception):
    '''This exception is raised, when no traces have been selected in the viewer 
    and we cannot fallback to using the current view.'''
    pass

class UserCancelled(Exception):
    '''This exception is raised, when the user has cancelled a snuffling dialog.'''
    pass

class SnufflingCallFailed(Exception):
    '''This exception is raised, when :py:meth:`Snuffling.fail` is called from :py:meth:`Snuffling.call`.'''


class SnufflingModule:
    '''Utility class to load/reload snufflings from a file.
    
    The snufflings are created by a user module which has a special function
    :py:func:`__snufflings__` which return the snuffling instances to be exported. The
    snuffling module is attached to a handler class, which makes use of the
    snufflings (e.g. :py:class:`pyrocko.pile_viewer.PileOverwiew` from ``pile_viewer.py``). The handler class must
    implement the methods ``add_snuffling()`` and ``remove_snuffling()`` which are used
    as callbacks. The callbacks are utilized from the methods :py:meth:`load_if_needed`
    and :py:meth:`remove_snufflings` which may be called from the handler class, when
    needed.
    '''
    
    mtimes = {}
    
    def __init__(self, path, name, handler):
        self._path = path
        self._name = name
        self._mtime = None
        self._module = None
        self._snufflings = []
        self._handler = handler
        
    def load_if_needed(self):
        filename = os.path.join(self._path, self._name+'.py')
        mtime = os.stat(filename)[8]
        sys.path[0:0] = [ self._path ]
        if self._module == None:
            try:
                self._module = __import__(self._name)
                for snuffling in self._module.__snufflings__():
                    self.add_snuffling(snuffling)
                    
            except:
                logger.error(_str_traceback())
                raise BrokenSnufflingModule(self._name)
                            
        elif self._mtime != mtime:
            logger.warn('reloading snuffling module %s' % self._name)
            settings = self.remove_snufflings()
            try:
                reload(self._module)
                for snuffling in self._module.__snufflings__():
                    self.add_snuffling(snuffling, reloaded=True)
                
                if len(self._snufflings) == len(settings):
                    for sett, snuf in zip(settings, self._snufflings):
                        snuf.set_settings(sett)


            except:
                logger.error(_str_traceback())
                raise BrokenSnufflingModule(self._name)            
            
        self._mtime = mtime
        sys.path[0:1] = []
    
    def add_snuffling(self, snuffling, reloaded=False):
        snuffling._path = self._path 
        snuffling.setup()
        self._snufflings.append(snuffling)
        self._handler.add_snuffling(snuffling, reloaded=reloaded)
    
    def remove_snufflings(self):
        settings = []
        for snuffling in self._snufflings:
            settings.append(snuffling.get_settings())
            self._handler.remove_snuffling(snuffling)
            
        self._snufflings = []
        return settings
    
class BrokenSnufflingModule(Exception):
    pass


class MyScrollArea(QScrollArea):

    def sizeHint(self):
        s = QSize()
        s.setWidth(self.widget().sizeHint().width())
        s.setHeight(30)
        return s

class SwitchControl(QCheckBox):
    def __init__(self, ident, default, *args):
        QCheckBox.__init__(self, *args)
        self.ident = ident
        self.setChecked(default)
        self.connect(self, SIGNAL('toggled(bool)'), self.sw_toggled)

    def sw_toggled(self, state):
        self.emit(SIGNAL('sw_toggled(PyQt_PyObject,bool)'), self.ident, state)

    def set_value(self, state):
        self.blockSignals(True)
        self.setChecked(state)
        self.blockSignals(False)

class ChoiceControl(QFrame):
    def __init__(self, ident, default, choices, name, *args):
        QFrame.__init__(self, *args)
        self.label = QLabel(name, self)
        self.label.setMinimumWidth(120)
        self.cbox = QComboBox(self)
        self.layout = QHBoxLayout(self)
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.cbox)
        
        self.ident = ident
        self.choices = choices
        for ichoice, choice in enumerate(choices):
            self.cbox.addItem(QString(choice))
        
        self.set_value(default)
        self.connect(self.cbox, SIGNAL('activated(int)'), self.choosen)
        
    def choosen(self, i):
        self.emit(SIGNAL('choosen(PyQt_PyObject,PyQt_PyObject)'), self.ident, self.choices[i])

    def set_value(self, v):
        self.cbox.blockSignals(True)
        for i, choice in enumerate(self.choices):
            if choice == v:
                self.cbox.setCurrentIndex(i)
        self.cbox.blockSignals(False)

