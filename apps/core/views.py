# Author: Pavel Studenik
# Email: pstudeni@redhat.com
# Date: 24.9.2013

from django.shortcuts import render_to_response, render
from django.template import RequestContext
from django.views.generic import TemplateView, View
from django.http import HttpResponseRedirect, Http404, HttpResponse
from django.db.models import Count
from django.db.models import Q
from django.core.paginator import Paginator
from django.conf import settings
from django.core import serializers
from django.template import Context, Template
from django.db import connection

from datetime import date, timedelta
from forms import FilterForm
# from json import JSONEncoder
import re, os, time
from copy import copy
import urllib
import json
import logging

from apps.core.models import *
from apps.core.utils.beaker import JobGen
from apps.core.utils.date_helpers import *
from forms import JobForm, GroupsForm
from apps.waiver.forms import WaiverForm
from apps.waiver.models import Comment
from apps.core.utils.beaker_import import *
from bs4 import BeautifulSoup

if sys.version_info < (2, 7):
    from ordereddict import OrderedDict
else:
    from collections import OrderedDict


logger = logging.getLogger(__name__)

def render_lable(data, rule):
    rule = "{%% load core_extras %%}%s" % rule
    template = Template(rule)
    context = Context(data)
    # print "%s - %s" % ( data, rule)
    return template.render(context)


def import_xml(request):
    # TODO: rewrite to standard View Class
    data = {}
    if request.POST and "textxml" in request.POST:
        xml = request.POST["textxml"]
        s = Parser(content=xml)
        if not s.status:
            data["error"] = s.error
        else:
            s.run()
            data["xml"] = xml
            data["job"] = s.job
            data["recipes"] = RecipeTemplate.objects.filter(jobtemplate=s.job)

    return render(request, 'import_xml.html', data)

def import_group(request):
    # TODO: rewrite to standard View Class
    data = { "forms": GroupsForm() }
    if request.POST and "group" in request.POST:
        forms = GroupsForm(request.POST)
        if forms.is_valid():
            data["group"] = forms.save()
        data["forms"] = forms
    return render(request, 'import_group.html', data)


def to_xml(request, id):
    # TODO: rewrite to standard View Class
    jg = JobGen()
    try:
        jobT = JobTemplate.objects.get(id=id)
    except JobTemplate.DoesNotExist:
        raise Http404
    xml = jg.getXML(jobT, reserve=True)
    try:
        soup = BeautifulSoup(xml, "xml")
    except:
        raise Exception("Bad xml format or something is bad")
    xml = soup.prettify()
    return render(request, 'job_xml.html',
           {'template': jobT, "xml": xml, "beaker": settings.BEAKER_SERVER})


def create_matrix(days):
    datearray = []
    index = 0
    while True:
        index += 1
        newday = date.today() - timedelta(days=index)
        # suturday and sunday were ignored
        if newday.weekday() in (4, 5):
            continue
        datearray.append(newday)  # .strftime("%Y-%m-%d"))
        if len(datearray) == days:
            break
    return list(reversed(datearray))


def statistic(request):
    content = "TODO"
    # we need create statistic page
    return HttpResponse(content, content_type='text/plain')


class ApiView(View):
    content_type = 'application/json'

    def getReschdulesOfRecipe(self, recipe):
        # Get all previous scheduled job of this job
        # TODO: predelat
        j_date = recipe.job.date
        date_range = (TZDatetime(*j_date.timetuple()[:3], hour=19, minute=0),
                      TZDatetime(*(j_date + timedelta(days=1))\
                                    .timetuple()[:3], hour=18, minute=55))
        rescheduled = Job.objects.filter(template=recipe.job.template,
                                         date__range=date_range)\
                                 .exclude(id=recipe.job.id)
        return [job.to_json() for job in rescheduled]

    def getRecipeComments(self, recipe):
        rComments = Comment.objects.filter(recipe=recipe, task__isnull=True)\
                .order_by('-created_date')
        return [comm.to_json() for comm in rComments]

    def getRecipeInfo(self, params, content):
        uid = params.get("recipe")
        if uid.startswith("R:"):
            uid = uid[2:]
        try:
            recipe = Recipe.objects.get(uid=uid)
        except Recipe.DoesNotExist:
            raise Http404

        content['results'] = recipe.get_result()
        content['recipe'] = recipe.to_json()
        content['job'] = recipe.job.to_json()
        content['job_name'] = recipe.job.template.whiteboard
        f2_tasks = Task.objects.filter(recipe=recipe).order_by('uid')
        content['task_progress'] = list()
        content['tasks'] = list()
        count = len(f2_tasks)
        counter = 0
        ecount = 0
        commentsCounter = 0
        last_result = -10
        sum = 0
        for task in f2_tasks:
            if task.result in [NEW, WARN, FAIL]:
                ecount += 1
                tComments = Comment.objects.filter(task=task, recipe=recipe)\
                                   .order_by('-created_date')
                if len(tComments) > 0:
                    commentsCounter += 1
                if ecount < 10:
                    tjson = task.to_json()
                    tjson['comments'] = [comm.to_json() for comm in tComments]
                    content['tasks'].append(tjson)
            tres = task.get_result_display()
            if task.statusbyuser == WAIVED:
                tres = task.get_statusbyuser_display()
            if tres != last_result:
                if last_result and counter > 0:
                    perc = max(counter * 100 / count, 1)
                    content['task_progress'].append((last_result,
                                                     perc, counter))
                    sum += perc
                counter = 0
            last_result = tres
            counter += 1
        perc = max(counter * 100 / count, 1)
        sum += perc
        if not recipe.job.is_running and sum < 100:
            perc += 100 - sum
        if sum > 100:
            perc -= (sum - 100)
        content['task_progress'].append((last_result, perc, counter))
        content['task_len'] = ecount
        content['comments_counter'] = commentsCounter
        content['reschduled'] = self.getReschdulesOfRecipe(recipe)
        content['comments'] = self.getRecipeComments(recipe)

    def getRecipeTasks(self, params, content):
        uid = params.get("recipe")
        from_ix = int(params.get("from", 0))
        if uid.startswith("R:"):
            uid = uid[2:]
        try:
            recipe = Recipe.objects.get(uid=uid)
        except Recipe.DoesNotExist:
            raise Http404
        f_tasks = Task.objects.filter(recipe=recipe).order_by('uid')
        if params.get("filter", 'errors') == 'errors':
            f_tasks = f_tasks.filter(result__in=[NEW, WARN, FAIL])
        f_tasks.order_by('uid')
        content['task_len'] = len(f_tasks)
        content['tasks'] = list()
        for task in f_tasks[from_ix:from_ix + 10]:
            tjson = task.to_json()
            comments = Comment.objects.filter(task=task, recipe=recipe)
            tjson['comments'] = [comm.to_json() for comm in comments]
            content['tasks'].append(tjson)

    def getTaskInfo(self, params, content):
        uid = params.get("task")
        from_ix = int(params.get("from", 0))
        if uid.startswith("T:"):
            uid = uid[2:]
        task = None
        try:
            task = Task.objects.get(uid=uid)
        except Recipe.DoesNotExist:
            raise Http404
        tComments = Comment.objects.filter(task=task).order_by('-created_date')
        content['task'] = task.to_json()
        content['task']['comments'] = [comm.to_json() for comm in tComments]
        content['results'] = task.get_result()
        recipe = task.recipe
        content['reschduled'] = self.getReschdulesOfRecipe(recipe)
        content['recipe'] = recipe.to_json()
        content['recipe']['comments'] = self.getRecipeComments(recipe)
        content['job'] = recipe.job.to_json()
        content['job_name'] = recipe.job.template.whiteboard

    def getOwnersList(self, params, content):
        owners = None
        key = params.get("key", False)
        if key:
            owners = Author.objects.filter(Q(name__contains=key) |
                                           Q(email__contains=key))
        else:
            owners = Author.objects.all()
        content['owners'] = [own.to_json() for own in owners] if owners else []

    def getGitChange(self, params, content):
        ids = params.get("ids", "").rstrip('|').split('|')
        test_history = TestHistory.objects.filter(id__in=ids).order_by('-date')
        content['changes'] = [change.to_json() for change in test_history]\
                                 if test_history else []

    def apiEvent(self, action, params):
        content = dict()
        if action == 'recipe-info':
            self.getRecipeInfo(params, content)
        elif action == 'recipe-tasks':
            self.getRecipeTasks(params, content)
        elif action == 'task-info':
            self.getTaskInfo(params, content)
        elif action == 'owners':
            self.getOwnersList(params, content)
        elif action == 'git-changes':
            self.getGitChange(params, content)
        return HttpResponse(json.dumps(content))

    def get(self, request, action, *args, **kwargs):
        return self.apiEvent(action, request.GET)

    def post(self, request, action, *args, **kwargs):
        return self.apiEvent(action, request.POST)


class JobsListView(TemplateView):
    template_name = 'jobs-list.html'

    def dispatch(self, request, *args, **kwargs):
        self.filters = {}
        self.forms = {}
        self.format = None
        return super(JobsListView, self).dispatch(request, *args, **kwargs)

    def filterEvent(self, parameters):
        self.forms['search'] = FilterForm(parameters)
        if "search" in parameters:
            if self.forms['search'].is_valid():
                self.filters['search'] = self.forms['search']\
                                             .cleaned_data["search"]
            else:
                self.filters['search'] = None
                self.forms['search'] = None
        self.format = parameters.get("format_output")

    def formEvent(self, parametrs):
        if "uids" in parametrs:
            self.forms['waiveFrom'] = WaiverForm(parametrs)
            if self.forms['waiveFrom'].is_valid():
                self.forms['waiveFrom'].save()
                self.forms['waiveFrom'].clean()
            else:
                print self.forms['waiveFrom'].errors

    def get(self, request, *args, **kwargs):
        self.filterEvent(request.GET)
        return super(self.__class__, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.formEvent(request.POST)
        self.get(request, *args, **kwargs)
        context = self.get_context_data(**kwargs)
        return super(self.__class__, self).render_to_response(context, **kwargs)

    def get_statistic(self, statistic):
            data = statistic["data"]
            head = [ it for it in data.keys() if it != "sum"]
            content = "date\t%s" % "\t".join(head)
            render = OrderedDict()
            for key, items in data.items():
                if key == "sum": continue
                for it in items:
                    count = data["sum"][it]
                    if not render.has_key(it):
                        render[it] = [100*items[it]/float(count),]
                    else:
                        render[it].append(100*items[it]/float(count))
            for key, value in render.items():
                row = "\t".join([str("%.2f" % it) for it in value])
                content += "\n%s\t%s" % (key , row)
            return content

    def render_to_response(self, context, **response_kwargs):
        # temporary return data for statis
        if self.format == "txt":
            content = self.get_statistic(context['statistic'])
            return HttpResponse(content, content_type='text/plain')
        return super(self.__class__, self).render_to_response(context, **response_kwargs)

    def prepare_matrix(self, jobs, recipes, label=None):
        data, reschedule = OrderedDict(), 0
        if not label:
            label = create_matrix(settings.PREVIOUS_DAYS)
        for job in jobs:
            job.recipes = dict()
            data[job.whiteboard] = job

        for recipe in recipes:
            whiteboard = recipe.job.template.whiteboard
            lb = render_lable(recipe.get_dict(), data[whiteboard].grouprecipes)
            tmp_recipe = data[whiteboard].recipes
            if not tmp_recipe.has_key(lb):
                tmp_recipe[lb] = dict()
                tmp_recipe[lb]["job"] = whiteboard
                tmp_recipe[lb]["days"] = OrderedDict()
                tmp_recipe[lb]["label"] = lb
                for d in label:
                    tmp_recipe[lb]["days"][d] = {"recipe": None, "schedule": []}
            labeldate = recipe.get_date().date()
            # recipe isn't in range of date # FIXME
            if not tmp_recipe[lb]["days"].has_key(labeldate): continue

            tmp_recipe[lb]["days"][labeldate]["recipe"] = recipe
            tmp_recipe[lb]["days"][labeldate]["schedule"].append(recipe.uid)
        return data

    def get_context_data(self, **kwargs):
        context = super(self.__class__, self).get_context_data(**kwargs)
        context['detailPanelHidden'] = self.request.COOKIES.get('detailHidden')
        context['detailPanelHeight'] = int(self.request.COOKIES.get('detailHeight', 0))
        context['detailActions'] = [Comment.ENUM_ACTION_WAIVED,
                                    Comment.ENUM_ACTION_RETURN,
                                    Comment.ENUM_ACTION_RESCHEDULE]
        context['waiveClass'] = Comment
        context['GITWEB_URL'] = settings.GITWEB_URL

        ### Forms ###


        ### daily ###
        context['label'] = create_matrix(settings.PREVIOUS_DAYS)

        jfilters = { "is_enable": True, "period": JobTemplate.DAILY}
        date_range = (TZDatetime(*context['label'][0].timetuple()[:6]),
                      TZDatetime(*context['label'][-1].timetuple()[:3], hour=23, minute=55)
                     )
        rfilters = { "job__template__is_enable": True,
                     "job__date__range": date_range,
                     "job__template__period": JobTemplate.DAILY}

        if self.filters.get('search'):
            jfilters["whiteboard__icontains"] = self.filters.get('search')
            rfilters["job__template__whiteboard__icontains"] = self.filters.get('search')

        jobs = JobTemplate.objects.filter(**jfilters).order_by("position")
        recipes = Recipe.objects.filter(**rfilters)\
                        .select_related("job", "job__template", "arch", "distro")\
                        .order_by("job__template__position", "uid")\
                        .annotate(Count('id'))
        context['data'] = self.prepare_matrix(jobs, recipes)

        ### weekly ###

        # create label
        cursor = connection.cursor()
        cursor.execute("""SELECT DISTINCT date("core_job"."date") AS "date" FROM "core_job"
                INNER JOIN "core_jobtemplate" ON ("core_job"."template_id" = "core_jobtemplate"."id")
                WHERE ("core_jobtemplate"."is_enable" = %s AND "core_jobtemplate"."period" = %s )
                ORDER BY date desc LIMIT %s""", [True, JobTemplate.WEEKLY, settings.PREVIOUS_DAYS, ],)
        # sqllite return unicode
        # postgresql return datetime
        udate = lambda a: a.date() if type(a) in (datetime,) else a
        context['labelweek'] = [udate(it[0]) for it in cursor.fetchall()];

        #FIXME
        try:
            date_range = (context['labelweek'][-1], datetime.now())
        except IndexError:
            date_range = (datetime.now(), datetime.now())

        jfilters = { "is_enable": True, "period": JobTemplate.WEEKLY}
        rfilters = { "job__template__is_enable": True,
                     "job__date__range": date_range,
                     "job__template__period": JobTemplate.WEEKLY}

        if self.filters.get('search'):
            jfilters["whiteboard__icontains"] = self.filters.get('search')
            rfilters["job__template__whiteboard__icontains"] = self.filters.get('search')

        jobs = JobTemplate.objects.filter(**jfilters)
        recipes = Recipe.objects.filter(**rfilters)\
                        .select_related("job", "job__template", "arch", "distro")\
                        .annotate(Count('id'))

        ### ORM doen't work correct ###

        # labelweek = [it.strftime("%Y-%m-%d") for it in Job.objects.values("date")\
        #        .filter(
        #             template__period=JobTemplate.WEEKLY,
        #             template__is_enable=True,
        #             date__lt=datetime.today().date(),
        #         )\
        #        .extra({'date_day': "date(date)"})\
        #        .values("date_day").order_by("date")\
        #        .annotate(Count('id'))\
        #        .dates("date", "day").order_by("-date")[:settings.PREVIOUS_DAYS]] # skip today - only previous day
        context['labelweek'].reverse()

        context['dataweek'] = self.prepare_matrix(jobs, recipes, context['labelweek'])

        if self.filters.get('search'):
            # statistic information
            cursor.execute("""SELECT date("core_job"."date") as job_date, "core_task"."result" as task_ressult, count("core_task"."result") from core_task
               LEFT JOIN "core_recipe" ON ("core_task"."recipe_id" = "core_recipe"."id")
               LEFT JOIN "core_job" ON ("core_recipe"."job_id" = "core_job"."id")
               LEFT JOIN "core_jobtemplate" ON ("core_jobtemplate"."id" = "core_job"."template_id")
               WHERE "core_job"."date" > %s AND "core_jobtemplate"."is_enable" = %s AND "core_jobtemplate"."period" = %s
               AND lower("core_jobtemplate"."whiteboard") LIKE lower(%s)
               GROUP BY date("core_job"."date"), "core_task"."result" ORDER BY job_date ASC, task_ressult """,
               [(datetime.now().date() - timedelta(days=14)).isoformat(), True, JobTemplate.DAILY, "%%%s%%" % self.filters.get('search')])
        else:
            cursor.execute("""SELECT date("core_job"."date") as job_date, "core_task"."result" as task_ressult, count("core_task"."result") from core_task
               LEFT JOIN "core_recipe" ON ("core_task"."recipe_id" = "core_recipe"."id")
               LEFT JOIN "core_job" ON ("core_recipe"."job_id" = "core_job"."id")
               LEFT JOIN "core_jobtemplate" ON ("core_jobtemplate"."id" = "core_job"."template_id")
               WHERE "core_job"."date" > %s AND "core_jobtemplate"."is_enable" = %s AND "core_jobtemplate"."period" = %s
               GROUP BY date("core_job"."date"), "core_task"."result" ORDER BY job_date ASC, task_ressult """,
               [(datetime.now().date() - timedelta(days=14)).isoformat(), True, JobTemplate.DAILY])

        data = cursor.fetchall()
        label = OrderedDict()
        T = lambda x : dict(RESULT_CHOICES)[x]
        for it in data:
            if not it[0] in label.keys():
                label.update({it[0]: 0})
        context['statistic'] = {"data": {"sum": copy(label)}, "label": copy(label)}
        for it in data:
            if not T(it[1]) in context['statistic']['data'].keys():
                context['statistic']['data'][T(it[1])] = copy(label)

            if it[0] in context['statistic']['data']["sum"]:
                pass
            context['statistic']['data'][T(it[1])][it[0]] = it[2]
            context['statistic']['data']["sum"][it[0]] += it[2]

        try:
            context['progress'] = CheckProgress.objects.order_by("-datestart")[0]
        except IndexError:
            context['progress'] = None
        # Search box
        context['forms'] = self.forms.get('search', FilterForm())
        # Waive Form
        author = Author.FromUser(self.request.user)
        if author:
            waiveform = WaiverForm(initial={"username": author.name})
        else:
            waiveform = WaiverForm()
        context['waiveForm'] = self.forms.get('waiveForm', waiveform)
        return context


class TestsListView(TemplateView):
    template_name = 'tests-list.html'

    # !!! INITIAL DATA in dispatch, this method call before get, post, delte, atd !!!
    def dispatch(self, request, *args, **kwargs):
        self.filters = {}
        self.forms = {}
        return super(TestsListView, self).dispatch(request, *args, **kwargs)

    def filterEvent(self, parameters, *args, **kwargs):
        self.filters = {'onlyfail': False}
        self.forms['search'] = FilterForm(parameters)
        if parameters.has_key('repo'):
            self.filters['repo_id'] = parameters.get('repo')
        if parameters.has_key('group'):
            self.filters['group_id'] = parameters.get('group')
        if kwargs.has_key('email'):
            self.filters['email'] = kwargs.get('email')
        if parameters.has_key("search"):
            self.filters['email'] = None
            if self.forms['search'].is_valid():
                self.filters['onlyfail'] = self.forms['search'].cleaned_data["onlyfail"]
                self.filters['search'] = self.forms['search'].cleaned_data["search"]
            else:
                self.forms['search'] = None

    def formEvent(self, parametrs):
        if parametrs.has_key("uids"):
            self.forms['waiveFrom'] = WaiverForm(parametrs)
            if self.forms['waiveFrom'].is_valid():
                self.forms['waiveFrom'].save()
                self.forms['waiveFrom'] = WaiverForm()
            else:
                print self.forms['waiveFrom'].errors

    def get(self, request, *args, **kwargs):
        self.filterEvent(request.GET, *args, **kwargs)
        return super(self.__class__, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.formEvent(request.POST)
        self.get(request, *args, **kwargs)
        context = self.get_context_data(**kwargs)
        return self.render_to_response(context)

    def render_to_response(self, context, **response_kwargs):
        # Search box
        context['forms'] = self.forms.get('search', FilterForm())
        author = Author.FromUser(self.request.user)
        if author:
            waiveform = WaiverForm(initial={"username": author.name})
        else:
            waiveform = WaiverForm()
        context['waiveForm'] = self.forms.get('waiveForm', waiveform)

        return super(self.__class__, self).render_to_response(context, **response_kwargs)

    def get_context_data(self, **kwargs):
        context = super(self.__class__, self).get_context_data(**kwargs)
        context['detailPanelHidden'] = self.request.COOKIES.get('detailHidden')
        context['detailPanelHeight'] = int(self.request.COOKIES.get('detailHeight', 0))
        context['detailActions'] = [Comment.ENUM_ACTION_WAIVED, ]
        context['waiveClass'] = Comment
        context['GITWEB_URL'] = settings.GITWEB_URL
        # Tests
        testFilter = dict()
        # testFilter['task__recipe__job__template__is_enable'] = True
        # Tasks
        taskFilter = dict()
        # taskFilter['recipe__job__template__is_enable'] = True
        # Owners
        owners = dict([(it.id, it) for it in Author.objects.filter(is_enabled=True).annotate(dcount=Count('test'))])
        # date Labels
        dates_label = create_matrix(settings.PREVIOUS_DAYS + 1)
        # History
        history = dict()
        minDate = currentDate() - timedelta(days=settings.PREVIOUS_DAYS + 7)
        changes = TestHistory.objects.filter(date__gt=minDate).select_related('test').annotate(dcount=Count('test'))
#TODO: Fix this feaure, the dependence packages
#        deptTests = dict()
#        for test in Test.objects.filter(dependencies__in = [it.test for it in changes]):
#            for depIt in test.dependencies.all():
#                if depIt.id not in deptTests:
#                    deptTests[depIt.id] = list()
#                deptTests[depIt.id].append(depIt)
        for change in changes:
            day = change.date.date()
            if change.date.hour > 20:
                day = day + timedelta(days=1)
            for lday in dates_label:
                if lday >= day:
                    day = lday
                    break;
            if not history.has_key(change.test.id):
                history[change.test.id] = dict()
            if not history[change.test.id].has_key(day):
                history[change.test.id][day] = list()
            history[change.test.id][day].insert(0, change)
#            depList = list() # Test.objects.filter(dependencies=change.test).values("id")
#            for depchange in depList:
#                if not history.has_key(depchange['id']):
#                    history[depchange['id']] = {}
#                if not history[depchange['id']].has_key(day):
#                    history[depchange['id']][day] = []
#                history[depchange['id']][day].append(change)
        # apply filter
        search = self.filters.get('search', False)
        if search and len(search) > 0:
            testFilter['name__icontains'] = search
            # taskFilter['test__name__icontains'] = search
        if self.filters.get('onlyfail', False):
            testFilter['task__result__in'] = [FAIL, ]
            # TODO: This is not good solution, it should be replaced
            day = date.today() - timedelta(days=1)
            testFilter['task__recipe__job__date__gt'] = day
        if self.filters.has_key('email') and self.filters["email"]:
            testFilter['owner__email'] = self.filters.get('email')
            # taskFilter['test__owner__email'] = self.filters.get('email')

        if self.filters.has_key('repo_id'):
            taskFilter['test__git__id'] = self.filters.get('repo_id')
            testFilter["git__id"] = self.filters.get('repo_id')
        if self.filters.has_key('group_id'):
            taskFilter['test__groups__id'] = self.filters.get('group_id')
            testFilter["groups__id"] = self.filters.get('group_id')

        date_range = (TZDatetime(*dates_label[0].timetuple()[:6]),
                      TZDatetime(*dates_label[-1].timetuple()[:3], hour=23, minute=55))
        taskFilter['recipe__job__date__range'] = date_range
        taskFilter['test__owner__is_enabled'] = True

        tasks = Task.objects.filter(**taskFilter).values(
            "recipe__job__template__whiteboard", "test__name", "recipe__resultrate", "recipe__arch__name",
            "test__owner__email", "recipe__uid", "recipe__job__date", "result", "id", "uid", "recipe",
            "statusbyuser", "recipe__job__template__grouprecipes", "recipe__arch__name",
            "recipe__whiteboard", "recipe__distro__name", "alias")\
        .order_by("test__owner__name", "recipe__job__template__whiteboard") \
        .annotate(Count('id'))

        # tests = Test.objects.filter(**testFilter).annotate(count = Count('id')).order_by("count", "name")
        testFilter['owner__is_enabled'] = True
        tests = Test.objects.filter(**testFilter) \
                .annotate(count_fail=Count('task__result'))\
                .annotate(Count('id')).order_by("-count_fail")

        paginator = Paginator(tests, settings.PAGINATOR_OBJECTS_ONPAGE)
        testlist = paginator.page(int(self.request.GET.get('page', 1)))
        ids = []
        data = dict()
        for it in testlist.object_list:
            email = owners[it.owner_id].email if it.owner_id else "unknow@redhat.com"
            if not data.has_key(email):
                data[email] = dict({"tests": OrderedDict(), 'owner': owners[it.owner_id]})
            ids.append(it.id)
            it.labels = OrderedDict()
            data[email]["tests"][it.name] = it

        # use only selected task
        tasks = tasks.filter(test__in=ids)
        stat = {"tasks": len(tasks), "tests": paginator.count}
        for it in tasks:
            if it['recipe__job__date'].weekday() in [4, 5]:
                continue
            id_email = it["test__owner__email"]
            # use for filters
            if not (data.has_key(id_email) and\
                data[id_email]["tests"].has_key(it["test__name"])):
                continue

            test = data[id_email]["tests"][it["test__name"]]
            # FIXME - better solution - duplicate code in models and here
            # print it
            lb = render_lable({
                "arch": it["recipe__arch__name"],
                "distro": it["recipe__distro__name"],
                "distro_label": it["recipe__distro__name"],
                "whiteboard": it["recipe__whiteboard"],
                "alias": it["alias"],
                }, it["recipe__job__template__grouprecipes"])
            test_label = (it["recipe__job__template__whiteboard"], lb)
            if not test.labels.has_key(test_label):
                test.labels[test_label] = OrderedDict()
                for day in dates_label:
                    test.labels[test_label][day] = None

            label = test.labels[test_label]

            labeldate = it["recipe__job__date"].date()
            if not label.has_key(labeldate): continue

            reschedule = 0
            if label[labeldate]:
                reschedule = label[labeldate].reschedule + 1
            label[labeldate] = Task(
                    id=it["id"],
                    uid=it["uid"],
                    result=it["result"],
                    statusbyuser=it["statusbyuser"],
                )
            label[labeldate].resultrate = it["recipe__resultrate"]
            label[labeldate].recipe_uid = "%s" % it["recipe__uid"]
            label[labeldate].reschedule = reschedule

        try:
            progress = CheckProgress.objects.order_by("-datestart")[0]
        except IndexError:
            progress = None

        urllist = filter(lambda (x, y): x != "page", self.request.GET.copy().items())

        if self.filters.get('onlyfail', False):
            context["tests_bad"] = tests[:10]
        context['data'] = data
        context["owners"] = owners
        context["label"] = dates_label
        context['tests'] = testlist
        context["paginator"] = paginator
        context['progress'] = progress
        context["stat"] = stat
        context["history"] = history
        context["urlstring"] = urllib.urlencode(dict(urllist))
        context['repos'] = Git.objects.all().order_by('name')
        context['groups'] = GroupOwner.objects.all().order_by('name')
        return context


class HomePageView(TemplateView):
    template_name = 'homepage.html'
    filters = {}
    forms = {}

    def get_context_data(self, **kwargs):
        context = super(self.__class__, self).get_context_data(**kwargs)
        try:
            context['progress'] = CheckProgress.objects.order_by("-datestart")[0]
        except IndexError:
            context['progress'] = None
        # Waiver
        comments = Comment.objects\
                            .filter(created_date__gt=datetime.today().date())\
                            .order_by("-created_date", "task", "recipe", "job")
        paginator = Paginator(comments, settings.PAGINATOR_OBJECTS_ONHOMEPAGE)
        context['waiver'] = paginator.page(int(self.request.GET.get('cpage', 1)))
        context['cpaginator'] = paginator
        history = TestHistory.objects.filter().order_by("-date")[:settings.PAGINATOR_OBJECTS_ONHOMEPAGE * 10]
        paginator = Paginator(history, settings.PAGINATOR_OBJECTS_ONHOMEPAGE)
        context['history'] = paginator.page(int(self.request.GET.get('hpage', 1)))
        context['hpaginator'] = paginator
        return context


class JobDetailView(TemplateView):
    template_name = 'detail.html'

    def get_context_data(self, **kwargs):
        context = super(self.__class__, self).get_context_data(**kwargs)

        job_id = kwargs["id"]
        oJobTmp = JobTemplate.objects.get(id=job_id)
        jobs_list = Job.objects.filter(template=oJobTmp).order_by("-date")

        paginator = Paginator(jobs_list, settings.PAGINATOR_OBJECTS_ONPAGE)
        jobs = paginator.page(int(self.request.GET.get('page', 1)))

        context["jobtemplate"] = oJobTmp
        context["jobs"] = jobs
        context['paginator'] = paginator
        return context


class TestDetailView(TemplateView):
    template_name = 'test-detail.html'

    def get_context_data(self, **kwargs):
        context = super(self.__class__, self).get_context_data(**kwargs)

        test_id = kwargs["id"]
        oTest = Test.objects.get(id=test_id)
        task_list = Task.objects.filter(test=oTest).order_by("-recipe__job__date")

        paginator = Paginator(task_list, settings.PAGINATOR_OBJECTS_ONPAGE)
        tasks = paginator.page(int(self.request.GET.get('page', 1)))

        context["jobtemplate"] = oTest
        context["tasks"] = tasks
        context['paginator'] = paginator
        return context


class JobsDiffView(TemplateView):
    template_name = 'diffs.html'

    def dispatch(self, request, *args, **kwargs):
        self.filters = {}
        self.forms = {}
        return super(JobsDiffView, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(self.__class__, self).get_context_data(**kwargs)

        if self.forms.has_key('jobs'):
            context["form"] = self.forms['jobs']
        else:
            context["form"] = JobForm()
        return context

    def formEvent(self, parametrs):
        jobform = JobForm(parametrs)
        self.forms['jobs'] = jobform

    def post(self, request, *args, **kwargs):
        self.formEvent(request.POST)
        context = self.get_context_data(**kwargs)

        if self.forms['jobs'].is_valid():
            context["diffs"] = self.forms['jobs'].compare()

            for it in context["diffs"]:
                print it

        return self.render_to_response(context)
