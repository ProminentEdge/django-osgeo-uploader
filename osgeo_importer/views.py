import json
import logging
import os
import shutil
from tempfile import mkdtemp
import zipfile

from django.contrib.auth.models import AnonymousUser
from django.core.files.temp import NamedTemporaryFile
from django.core.urlresolvers import reverse_lazy
from django.forms.forms import Form
from django.http import HttpResponse
from django.views.generic import FormView, ListView, TemplateView
from django.views.generic.base import View

from osgeo_importer.utils import import_all_layers

from .forms import UploadFileForm
from .importers import OSGEO_IMPORTER, VALID_EXTENSIONS
from .inspectors import OSGEO_INSPECTOR
from .models import UploadedData, UploadFile
from .utils import import_string, ImportHelper


OSGEO_INSPECTOR = import_string(OSGEO_INSPECTOR)
OSGEO_IMPORTER = import_string(OSGEO_IMPORTER)

logger = logging.getLogger(__name__)


class JSONResponseMixin(object):
    """
    A mixin that can be used to render a JSON response.
    """
    def render_to_json_response(self, context, **response_kwargs):
        """
        Returns a JSON response, transforming 'context' to make the payload.
        """
        return HttpResponse(
            self.convert_context_to_json(context),
            content_type='application/json',
            **response_kwargs
        )

    def convert_context_to_json(self, context):
        """
        Convert the context dictionary into a JSON object
        """
        # Note: This is *EXTREMELY* naive; in reality, you'll need
        # to do much more complex handling to ensure that arbitrary
        # objects -- such as Django model instances or querysets
        # -- can be serialized as JSON.
        return json.dumps(context)


class JSONView(JSONResponseMixin, TemplateView):
    def render_to_response(self, context, **response_kwargs):
        return self.render_to_json_response(context, **response_kwargs)


class UploadListView(ListView):
    model = UploadedData
    template_name = 'osgeo_importer/uploads-list.html'
    queryset = UploadedData.objects.all()


class FileAddView(ImportHelper, FormView, JSONResponseMixin):
    form_class = UploadFileForm
    success_url = reverse_lazy('uploads-list')
    template_name = 'osgeo_importer/new.html'
    json = False

    def form_valid(self, form):
        upload = self.upload(form.cleaned_data['file'], self.request.user)
        files = [f for f in form.cleaned_data['file']]
        self.configure_upload(upload, files)

        if self.json:
            return self.render_to_json_response({'state': upload.state, 'id': upload.id,
                                                 'count': UploadFile.objects.filter(upload=upload.id).count()})

        return super(FileAddView, self).form_valid(form)

    def render_to_response(self, context, **response_kwargs):
        # grab list of valid importer extensions for use in templates
        context["VALID_EXTENSIONS"] = ", ".join(VALID_EXTENSIONS)

        if self.json:
            context = {'errors': context['form'].errors}
            return self.render_to_json_response(context, **response_kwargs)

        return super(FileAddView, self).render_to_response(context, **response_kwargs)


class OneShotImportDemoView(TemplateView):
    template_name = 'osgeo_importer/one_shot_demo/one_shot.html'


def save_zip_contents(zip_file, to_dir):
    """ Saves the uncompressed contents of *zip_file* in *to_dir*, maintaining the directory structure
        saved in the zip file.
    """


class OneShotFileUploadView(ImportHelper, View):
    def post(self, request):
        if len(request.FILES) != 1:
            resp = 'Sorry, must be one and only one file'
        else:
            file_key = request.FILES.keys()[0]
            file = request.FILES[file_key]
            if file.name.split('.')[-1] != 'zip':
                resp = 'Sorry, only a a zip file is allowed'
            else:
                file.seek(0, 2)
                filesize = file.tell()
                file.seek(0)
                z = zipfile.ZipFile(file)
                owner = request.user
                ud = UploadedData(user=owner, name=file.name)
                try:
                    tempdir = mkdtemp()
                    z.extractall(tempdir)
                    filelist = [open(os.path.join(tempdir, member_name), 'rb') for member_name in z.namelist()]
                    self.configure_upload(ud, filelist)
                    import_all_layers(ud)
                finally:
                    shutil.rmtree(tempdir)

                resp = 'Got file "{}" of length: {} containing: {}'.format(file.name, filesize, z.namelist())

        print(resp)
        return HttpResponse(resp)
