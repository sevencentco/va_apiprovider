from collections import defaultdict
from collections import namedtuple
from sanic import Blueprint
from sanic import Blueprint, response

from .views import ModelView

class IllegalArgumentError(Exception):
    pass

#: The set of methods which are allowed by default when creating an API
READONLY_METHODS = frozenset(('GET', ))

RestInfo = namedtuple('RestInfo', ['db', 'universal_preprocess', 'universal_postprocess'])

class APIProvider(object):
    name = "restapi"
    APINAME_FORMAT = '{0}api'
    BLUEPRINTNAME_FORMAT = '{0}{1}'
    view_cls = None
    
    @staticmethod
    def _next_blueprint_name(blueprints, basename):
        
        # blueprints is a dict whose keys are the names of the blueprints
        existing = [name for name in blueprints if name.startswith(basename)]
        # if this is the first one...
        if not existing:
            next_number = 0
        else:
            b = basename
            existing_numbers = [int(n.partition(b)[-1]) for n in existing]
            next_number = max(existing_numbers) + 1
        return APIProvider.BLUEPRINTNAME_FORMAT.format(basename, next_number)
    
    @staticmethod
    def api_name(collection_name):
        return APIProvider.APINAME_FORMAT.format(collection_name)
    
    def __init__(self, name="restapi", app=None, **kw):
        self.name = name
        self.app = app
        self.apis_to_create = defaultdict(list)
        self.created_apis_for = {}
        if self.app is not None:
            self.init_app(self.app, **kw)            
            
    def init_app(self, app, view_cls=ModelView, preprocess=None, postprocess=None, db=None, *args, **kw):
        # if not hasattr(app, 'extensions'):
        #     app.extensions = {}
        if not hasattr(app, "ctx"):
            app.ctx = type("C", (), {})()
        if not hasattr(app.ctx, "extensions") or app.ctx.extensions is None:
            app.ctx.extensions = {}
        ###
        if self.name in app.ctx.extensions:
            raise ValueError(self.name + ' has already been initialized on'
                             ' this application: {0}'.format(app))
        app.ctx.extensions[self.name] = RestInfo(db, preprocess or {}, postprocess or {})
        
        if app is not None:
            self.app = app
            
        if view_cls is not None:
            self.view_cls = view_cls
            
        apis = self.apis_to_create
        to_create = apis.pop(app, []) + apis.pop(None, [])
        
        for args, kw in to_create:
            blueprint = self.create_api_blueprint(app=app, *args, **kw)
            app.blueprint(blueprint)
            
    def create_api_blueprint(self, model=None, collection_name=None, app=None, methods=READONLY_METHODS,
                             url_prefix='/api', exclude_columns=None,
                             include_columns=None, include_methods=None,
                             results_per_page=10, max_results_per_page=100,
                             preprocess=None, postprocess=None, primary_key=None, *args, **kw):
        if collection_name is None:
            msg = ('collection_name is not valid.')
            raise IllegalArgumentError(msg)
            
        if exclude_columns is not None and include_columns is not None:
            msg = ('Cannot simultaneously specify both include columns and'
                   ' exclude columns.')
            raise IllegalArgumentError(msg)
        
        if app is None:
            app = self.app
            
        restapi_ext = app.ctx.extensions[self.name]
        
        methods = frozenset((m.upper() for m in methods))
        no_instance_methods = methods & frozenset(('POST', ))
        instance_methods = methods & frozenset(('GET', 'PATCH', 'DELETE', 'PUT'))
        possibly_empty_instance_methods = methods & frozenset(('GET', ))
        
        # the base URL of the endpoints on which requests will be made
        collection_endpoint = '/{0}'.format(collection_name)
        
        apiname = APIProvider.api_name(collection_name)
        
        preprocessors_ = defaultdict(list)
        postprocessors_ = defaultdict(list)
        preprocessors_.update(preprocess or {})
        postprocessors_.update(postprocess or {})
        
        api_view = self.view_cls.as_view(model=model, collection_name=collection_name,exclude_columns=exclude_columns,\
                            include_columns=include_columns, include_methods=include_methods,\
                            results_per_page=results_per_page, max_results_per_page=max_results_per_page, \
                            preprocess=preprocessors_, postprocess=postprocessors_, primary_key=primary_key,\
                            db=restapi_ext.db)
                         
        blueprintname = APIProvider._next_blueprint_name(app.blueprints, apiname) 
        bp_route_name = blueprintname + "_nim" #### no_instance_methods
        blueprint = Blueprint(blueprintname, url_prefix=url_prefix)
        blueprint.add_route(handler=api_view, uri=collection_endpoint,
                methods=no_instance_methods, name=bp_route_name,)
 
        #DELETE, GET, PUT
        bp_route_name = blueprintname + "_im" #### instance_methods
        instance_endpoint = '{0}/<instid>'.format(collection_endpoint)
        blueprint.add_route(handler=api_view, uri=instance_endpoint,
                methods=instance_methods, name=bp_route_name,)
        
        return blueprint
    
    def create_api(self, *args, **kw):
        if 'app' in kw:
            if self.app is not None:
                msg = ('Cannot provide a application in the APIProvider'
                       ' constructor and in create_api(); must choose exactly'
                       ' one')
                raise IllegalArgumentError(msg)
            app = kw.pop('app')
            if self.name in app.ctx.extensions:
                blueprint = self.create_api_blueprint(app=app, *args, **kw)
                app.blueprint(blueprint)
            else:
                self.apis_to_create[app].append((args, kw))
        else:
            if self.app is not None:
                app = self.app
                blueprint = self.create_api_blueprint(app=app, *args, **kw)
                app.blueprint(blueprint)
            else:
                self.apis_to_create[None].append((args, kw))
                