#!/bin/python
# -*- coding: utf-8 -*-

# Author: Pavel Studenik
# Email: pstudeni@redhat.com
# Date: 24.9.2013

import urllib2
import os
import sys
import re
import git
import logging
import gitconfig
from django.db import models
from datetime import datetime
from django.conf import settings
from django.db.models import Count
from django.core.urlresolvers import reverse
from apps.core.utils.date_helpers import toUTC, currentDate, TZDateTimeField
from taggit.managers import TaggableManager
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from apps.taskomatic.models import TaskPeriodSchedule

logger = logging.getLogger(__name__)

UNKNOW = 0
ABOART = 1
WAIT = 2
WARN = 3
FAIL = 4
PASS = 5
NEW = 6
CANCEL = 7
SCHEDULED = 8
PANIC = 9
FAILINSTALL = 10
RESULT_CHOICES = (
    (UNKNOW, "unknow"),
    (ABOART, "aborted"),
    (CANCEL, "cancelled"),
    (WAIT, "waiting"),
    (SCHEDULED, "scheduled"),
    (NEW, "new"),
    (WARN, "warn"),
    (WARN, "warning"),
    (FAIL, "fail"),
    (PASS, "pass"),
    (PANIC, "panic"),
    (FAILINSTALL, "failinstall"),
)

NONE = 0
WAIVED = 11
USERSTATUS_CHOICES = (
    (NONE, u"none"),
    (WAIVED, u"waived"),
)

RETURN = 0
RETURNWHENGREEN = 1
RESERVED = 2
EVENT_FINISH_ENUM = (
    ( RETURN, "return" ),
    ( RETURNWHENGREEN, "return when ok" ),
    ( RESERVED, "sererved system" )
)

class Arch(models.Model):
    name = models.CharField(max_length=32, unique=True)

    def __unicode__(self):
        return self.name


class Distro(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __unicode__(self):
        return self.name


class ObjParams():
    def get_params(self):
        params = {}
        for it in self.params.split("\n"):
            if not it: continue
            try:
                n, v = it.strip().split("=")
                params.update({n: v})
            except ValueError:
                logger.warning("valid params: %s" % self.params.split("\n"))
        return params

    def clean(self):
        self.params = self.params.strip()
        try:
            self.get_params()
        except ValueError:
            raise ValidationError("Non-valid notation, please use a=b")


class Git(models.Model):
    name = models.CharField(max_length=64, blank=True, null=True)
    localurl = models.CharField(max_length=255)
    url = models.CharField(max_length=255, unique=True)
    path_absolute = None
    cmd = None
    log = None
    groups = None

    def __unicode__(self):
        return self.name

    def to_json(self):
        return {
            'name': self.name,
        }

    @staticmethod
    def getGitFromFolder(folder):
        """
            Create/load Git object based git repository (folder)
        """
        config = gitconfig.config("%s/.git/config" % folder)
        for it in config.list:
            if it.startswith("remote.origin.url"):
                url = re.sub(r'.*(@|//)', '', it)
                name = os.path.basename(folder)
                oGit, new = Git.objects.get_or_create(url=url, defaults={
                                                        "name": name
                                                        })
                oGit.path_absolute = folder
                if not new and oGit.name != name:
                    oGit.name = name
                    oGit.save()
                return oGit
        return None

    def refresh(self):
        """
          Refresh (git pull) repository
        """
        git = self.__getGitCmd()
        # git.fetch()
        git.reset('--hard', 'HEAD')
        counter = 5
        try:
            git.pull()
            return
        except:
            if counter == 0:
                self.__getLog().warning("Problem with pulling of "
                                        "the repository '%s'" % self.name)
                return
            counter -= 1

    def updateInformationsAboutTests(self):
        """
          Update informations about tests from Makefiles.
        """
        git = self.__getGitCmd()
        # git ls-files --full-name *Makefile
        mkFiles = git.ls_files('--full-name', '*Makefile')
        for mkFile in mkFiles.splitlines():
            folder = os.path.dirname(mkFile)
            info = self.__parseMakefile("%s/%s" % (self.path_absolute, mkFile))
            if 'Name' not in info:
                self.__getLog().warning("The test '%s' doesn't contain"
                                        " Name in Makefile" % folder)
                continue
            owner = Author.parseAuthor(info.get('Owner'))
            name = re.sub('\s+.*', '', info.get('Name'))
            test = None
            tests = Test.objects.filter(folder=folder, git=self).order_by('id')
            if len(tests) > 0:
                test = tests[0]
                test.name = name
                if len(tests) > 1:
                    # This is here, because we have got more records in DB for
                    # the one test, when the name of test was changed.
                    testH = TestHistory.objects.filter(test=test)
                    for it in tests[1:]:
                        for it2 in TestHistory.objects.filter(test=it):
                            if it2 in testH:
                                it2.delete()
                            else:
                                it2.test = test
                                it2.save()
                        deps = Test.objects.filter(dependencies=it)
                        for it3 in deps:
                            it3.dependencies.remove(it)
                            if test not in it3.dependencies:
                                it3.dependencies.append(test)
                            it3.save()
                        it.delete()
            else:
                test, status = Test.objects.get_or_create(name=name, defaults={
                                                          "git": self})
            test.owner = owner
            test.folder = folder
            if 'Description' in info and \
                test.description != info.get('Description'):
                test.description = info.get('Description')
            if 'TestTime' in info and test.time != info.get('TestTime'):
                test.time = info.get('TestTime')
            if 'Type' in info and test.type != info.get('Type'):
                test.type = info.get('Type')
            if 'RunFor' in info:
                self.__updateGroups(test, info.get('RunFor'))
            self.__updateDependences(test, info.get('RhtsRequires'))
            test.save()

    def checkHistory(self):
        """
          Check history of known tests
        """
        git = self.__getGitCmd()
        # git log --decorate=full --since=1 --simplify-by-decoration /
        #         --pretty=%H|%aN|%ae|%ai|%d --follow HEAD
        checkDays = int(settings.CHECK_COMMMITS_PREVIOUS_DAYS)
        if not checkDays:
            checkDays = 1
        tests = Test.objects.filter(git=self).only('folder')
        for test in tests:
            if not test.folder:
                self.__getLog().warning("The GIT folder for test '%s'"
                                        " is not declared." % test.name)
                continue
            rows = git.log('--decorate=full',
                           '--since=%s.days' % checkDays,
                           '--simplify-by-decoration',
                           '--pretty=%H|%aN|%ae|%ai|%d',
                           '--follow',
                           'HEAD',
                           "%s/%s" % (self.path_absolute, test.folder))\
                      .split('\n')
            self.__saveCommits(test, rows)

    def __getGitCmd(self):
        if not self.path_absolute:
            raise Exception("Missing the absolute path to repository")
        if not self.cmd:
            self.cmd = git.cmd.Git(self.path_absolute)
        return self.cmd

    def __getLog(self):
        if not self.log:
            self.log = logging.getLogger()
        return self.log

    def __getVariables(self, rows):
        lex = dict()
        for row in rows:
            rr = re.match(r"^(export\s+)?([A-Za-z0-9_]+)=\"?([^#]*)\"?(#.*)?$",
                          row)
            if rr:
                lex[rr.group(2)] = re.sub(r'\$\(?([A-Za-z0-9_]+)\)?',
                                          lambda mo: lex.get(mo.group(1), ''),
                                          rr.group(3)).strip()
        return lex

    def __getMakefileInfo(self, rows, lex):
        info = dict()
        for row in rows:
            rr = re.match(r"^\s*@echo\s+\"([A-Za-z0-9_]+):\s+([^\"]*)\".*$",
                          row)
            if rr:
                key = rr.group(1)
                val = rr.group(2)
                if key in info:
                    if not isinstance(info[key], list):
                        oval = info[key]
                        info[key] = list()
                        info[key].append(oval)
                    info[key].append(val)
                else:
                    info[key] = re.sub(r'\$\(?([A-Za-z0-9_]+)\)?',
                                       lambda mo: lex.get(mo.group(1), ''),
                                       val).strip()
        return info

    def __parseMakefile(self, mkfile):
        rows = list()
        with open(mkfile) as fd:
            rows = fd.readlines()
        return self.__getMakefileInfo(rows, self.__getVariables(rows))

    def __updateGroups(self, test, row):
        if not self.groups:
            self.groups = list()
            for it in GroupOwner.objects.all():
                self.groups.append(it)
        res = list()
        if isinstance(row, list):
            row = " ".join(row)
        for it in self.groups:
            if row.find(it.name) >= 0:
                res.append(it)
        if len(res) > 0:
            # Remove unsupported groups
            for group in test.groups.all():
                if group not in res:
                    test.groups.remove(group)
                else:
                    res.remove(group)
            # Add new groups
            for group in res:
                test.groups.add(group)


    def __updateDependences(self, test, rows):
        if not rows:
            rows = list()
        dependencies = list()
        for row in rows:
            depName = re.sub(r'(test\(|\))', '', row).strip()
            depTest = Test.objects.filter(name__endswith=depName).only('name',
                                                                       'git')
            if len(depTest) > 0 and depTest[0] not in dependencies:
                dependencies.append(depTest[0])
        dep_old = list(test.dependencies.all())
        # Adding new dependencies
        for dep in dependencies:
            if dep == test:
                continue
            if dep in dep_old:
                dep_old.remove(dep)
            else:
                test.dependencies.add(dep)
        # Removing old/unsupported dependencies
        for dep in dep_old:
            test.dependencies.remove(dep)

    def __saveCommits(self, test, rows):
        # 1731d5af22c22469fa7b181d1e33cd52731619a0|Jiri Mikulka|
        # jmikulka@redhat.com|2013-01-31 17:45:06 +0100|
        # (tag: RHN-Satellite-CoreOS-RHN-Satellite-Other-Sanity-spacewalk-
        #   create-channel-1_0-2)
        testName = test.name
        if testName.startswith('/'):
            testName = testName[1:]
        testName = test.name.replace('/', '-')
        for row in rows:
            if len(row) == 0:
                continue
            data = dict()
            chash, name, email, date, tag = row.split('|')
            if tag:
                res = re.search(r".*%s-([0-9\_\-]+)[^0-9\_\-].*" % testName,
                                tag)
                if res:
                    data['version'] = res.group(1)
            author, status = Author.objects\
                  .get_or_create(email=email, defaults={"name": name})
            data['author'] = author
            data['date'] = toUTC(date)
            commit, status = TestHistory.objects\
                  .get_or_create(commit=chash, test=test, defaults=data)
            return commit

    def get_count(self):
        return len(Test.objects.filter(git__id=self.id))


class Author(models.Model):
    DEFAULT_AUTHOR = ("Unknown", "unknow@redhat.com")
    name = models.CharField(max_length=255, unique=False)
    email = models.EmailField(default=DEFAULT_AUTHOR[1])
    is_enabled = models.BooleanField(default=True)

    def __unicode__(self):
        return "%s <%s>" % (self.name, self.email)

    def to_json(self):
        return {
            'name': self.name,
            'email': self.email
        }

    @staticmethod
    def FromUser(user):
        if user.is_anonymous():
            return None
        try:
            return Author.objects.get(email=user.email)
        except Author.DoesNotExist:
            return None

    @staticmethod
    def parseAuthor(row):
        """
           Parse author from line "name <email@exmaple.com>"
        """
        rr = re.search(r"((?P<name>[^@<]*)(\s|$)\s*)?"
                       r"<?((?P<email>[A-z0-9_\.\+]+"
                       r"@[A-z0-9_\.]+\.[A-z]{2,3}))?>?", row)
        name = None
        email = None
        # Parse owner
        if rr and rr.group('name'):
            name = rr.group('name').strip()
        if rr and rr.group('email'):
            email = rr.group('email').strip()
        # Tring find by email
        if email and not name:
            auths = Author.objects.filter(email=email)\
                          .exclude(name=Author.DEFAULT_AUTHOR[0])
            if len(auths) > 0:
                return auths[0]
        # Tring find by name
        if not email and name:
            auths = Author.objects.filter(name=name)\
                          .exclude(email=Author.DEFAULT_AUTHOR[1])
            if len(auths) > 0:
                return auths[0]
        if not email:
            email = Author.DEFAULT_AUTHOR[1]
        if not name:
            name = Author.DEFAULT_AUTHOR[0]
        owner, status = Author.objects\
            .get_or_create(email=email, defaults={'name': name})
        return owner


class GroupOwner(models.Model):
    name = models.CharField(max_length=255, unique=True)
    owners = models.ManyToManyField(Author, null=True)
    email_notification = models.BooleanField(default=True)

    def __unicode__(self):
        return self.name

    class Meta:
        ordering = ["name", ]


class Test(models.Model):
    name = models.CharField(max_length=255, unique=True)
    git = models.ForeignKey(Git, blank=True, null=True)
    owner = models.ForeignKey(Author, null=True)
    description = models.TextField(blank=True, null=True)
    dependencies = models.ManyToManyField("Test", blank=True)
    time = models.CharField(max_length=6, blank=True, null=True)
    type = models.CharField(max_length=32, blank=True, null=True)
    folder = models.CharField(max_length=256, blank=True, null=True)
    is_enable= models.BooleanField("enable", default=True)
    groups = models.ManyToManyField(GroupOwner, blank=True)

    class Meta:
        ordering = ["name", ]

    def __unicode__(self):
        return self.name

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        if self.id and other.id:
            return self.id == other.id
        return self.name == other.name and self.git == other.git

    def to_json(self):
        return {
            'name': self.name,
            'git': self.git.to_json() if self.git else None,
            'owner': self.owner.to_json() if self.owner else None,
            'description': self.description,
        }

    def get_absolute_url(self):
        return "%s#%s" % (reverse("tests-email", args=[self.owner.email]),
                          self.name)

    def get_detail_url(self):
        return "%s" % reverse("test-detail", args=[self.id])

    def get_reposituory_url(self):
        if not self.git:
            return None
        return "%s/tree/HEAD:/%s" % (self.git.localurl, self.folder)


class TestHistory(models.Model):
    test = models.ForeignKey(Test)
    version = models.CharField(max_length=24, null=True)
    date = TZDateTimeField()
    author = models.ForeignKey(Author, null=True)
    commit = models.CharField(max_length=64, null=True)

    def __unicode__(self):
        return "%s %s" % (self.commit, self.date)

    def to_json(self):
        return {
            'version': self.version,
            'test': self.test.to_json() if self.test else None,
            'author': self.author.to_json() if self.author else None,
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'commit': self.commit,
            'url': self.get_absolute_url()
        }

    def get_absolute_url(self):
        # FIXME maybe create url from db record
        # for example: return self.test.git.url % self.commit
        return "%s/commitdiff/%s" % (self.test.git.localurl, self.commit)

class System(models.Model):
    hostname = models.CharField(max_length=255, blank=True)
    ram = models.IntegerField(null=True, blank=True)
    cpu = models.CharField(max_length=255, blank=True)
    hdd = models.CharField(max_length=255, blank=True)
    parent = models.ForeignKey("System", null=True, blank=True)
    group = models.SmallIntegerField(null=True, blank=True)

    def __unicode__(self):
        return self.hostname

    def to_json(self):
        return {
            'hostname': self.hostname,
            'ram': self.ram,
            'cpu': self.cpu,
            'hdd': self.hdd,
            'parent': self.parent.hostname if self.parent else None,
            'group': self.group
        }


class JobTemplate(models.Model):
    DAILY = 0
    WEEKLY = 1
    PERIOD_ENUM = (
        (DAILY, "daily"),
        (WEEKLY, "weekly")
    )
    whiteboard = models.CharField(max_length=255, unique=True)
    is_enable = models.BooleanField(default=False)
    event_finish = models.SmallIntegerField(choices=EVENT_FINISH_ENUM, default=RETURN)
    period = models.SmallIntegerField(choices=PERIOD_ENUM, default=DAILY)
    position = models.SmallIntegerField(default=0)
    grouprecipes = models.CharField(max_length=255, null=False, blank=True,
                    help_text="example: {{arch}} {{whiteboard|nostartsdate}}")
    tags = TaggableManager(blank=True)

    def __unicode__(self):
        return self.whiteboard

    def save(self, *args, **kwargs):
        model = self.__class__

        if self.position is None:
            # Append
            try:
                last = model.objects.order_by("period", "-position")[0]
                self.position = last.position + 1
            except IndexError:
                # First row
                self.position = 0

        return super(JobTemplate, self).save(*args, **kwargs)

    class Meta:
        ordering = ('period', 'position',)

    @models.permalink
    def get_absolute_url(self):
        return ("beaker-xml", [self.id])

    def admin_url(self):
        content_type = ContentType.objects.get_for_model(self.__class__)
        return reverse("admin:%s_%s_change" % (content_type.app_label, content_type.model), args=(self.id,))

    def is_return(self):
        return ( self.event_finish == RETURN )



class DistroTemplate(models.Model):
    name = models.CharField(max_length=255, blank=True, help_text="Only alias")
    family = models.CharField(max_length=255, blank=True, null=True)
    variant = models.CharField(max_length=255, blank=True, null=True)
    distroname = models.CharField(max_length=255, blank=True, null=True, \
        help_text="If field is empty, then it will use latest compose.")

    def __unicode__(self):
        return self.name

    def tpljobs_counter(self):
        return RecipeTemplate.objects.filter(distro=self).count()

    class Meta:
        ordering = ('name', 'distroname',)


class RecipeTemplate(models.Model, ObjParams):
    NONE, RECIPE_MEMBERS, STANDALONE = 0, 1, 2
    ROLE_ENUM = (
        (NONE, "None"),
        (RECIPE_MEMBERS, "RECIPE_MEMBERS"),
        (STANDALONE, "STANDALONE"),
    )

    jobtemplate = models.ForeignKey(JobTemplate, related_name="trecipes")
    name = models.CharField(max_length=255, blank=True)
    kernel_options = models.CharField(max_length=255, blank=True)
    kernel_options_post = models.CharField(max_length=255, blank=True)
    ks_meta = models.CharField(max_length=255, blank=True)
    role = models.SmallIntegerField(choices=ROLE_ENUM, default=NONE)
    arch = models.ManyToManyField(Arch)
    memory = models.CharField(max_length=255, blank=True)
    disk = models.CharField(max_length=255, blank=True, help_text="Value is in GB")
    hvm = models.BooleanField(default=False)
    params = models.TextField(blank=True)
    distro = models.ForeignKey(DistroTemplate)
    is_virtualguest = models.BooleanField(default=False)
    virtualhost = models.ForeignKey("RecipeTemplate", null=True, blank=True,
                                    related_name="virtualguests")
    schedule = models.CharField("schedule period", max_length=255, blank=True)

    def __unicode__(self):
        if not self.name:
            return "(empty)"
        else:
            return self.name

    def set_role(self, value):
        try:
            self.role = [it[0] for it in self.ROLE_ENUM if value == it[1]][0]
        except IndexError:
            print "VALUE %s isn't possible to set as ROLE" % value

    def get_role(self):
        return [it[1] for it in self.ROLE_ENUM if self.role == it[0]][0]

    def get_arch(self):
        return self.arch.all()

    def archs(self):
        return ", ".join([it.name for it in self.get_arch()])

    def get_tasks(self):
        return self.tasks.filter(test__is_enable=True).select_related("test").order_by("priority")

    # TODO: Remove Arch rotation
    # This solution of rotation of Arch is not good idea.
    # Better idea is TasksList.
    def getArchsForToday(self):
        """
            Return list of architecures for today
        """

        # Weekday as a decimal number [0(Sunday),6].
        weekday = int(datetime.now().strftime("%w"))
        archs = [it.name for it in self.arch.all()]
        schedule = self.__parse_schedule_period(self.schedule)

        res = list()
        for it in schedule:
            if ((it[2] == weekday and it[1]) or \
                (it[2] != weekday and not it[1])):
                res.append(Arch.objects.get(name=it[0]))
        if res: return res

        # if empty return all archs
        return self.get_arch()


    def parse(self, st):
        return self.__parse_schedule_period(st)

    def __parse_schedule_period(self, string):
        # i386: 1; s390x: 2; x86_64: 3; i386: 4; x86_64: 5,6,0
        # x86_64: !5; i386: 5
        if not string:
            return []
        data = []
        for it in string.split(";"):
            if not it.strip(): continue
            try:
                key, val = it.split(":")
            except ValueError:
                raise ValueError("Parse error: %s" % it)
            val = val.strip()
            op = True
            if val.startswith("!"):
                # negation - complement [0-6] for example
                # !1 - run every day expect monday
                val = val[1:]
                op = False
            vals = [it.strip() for it in val.split(",")]
            key = key.strip()
            for val in vals:
                if not val:
                    continue
                data.append((key, op, int(val.strip())))
        return data

    def save(self, *args, **kwargs):
        self.__parse_schedule_period(self.schedule)
        super(self.__class__, self).save(*args, **kwargs)

    class Meta:
        ordering = ('name',)

    def is_return(self):
        return self.jobtemplate.is_return()

    def is_reserve(self):
        return not self.is_return()

    def is_enabled(self):
        return self.jobtemplate.is_enable


class TaskRoleEnum(models.Model):
    name = models.CharField(max_length=255, blank=True)

    def __unicode__(self):
        return self.name

    class Meta:
        ordering = ('name',)


class GroupTemplate(models.Model):
    name = models.CharField(max_length=64)
    description = models.TextField(blank=True, null=True)
    
    def __unicode__(self):
        return self.name


class GroupTaskTemplate(ObjParams, models.Model):
    group = models.ForeignKey(GroupTemplate, related_name="grouptasks")
    recipe = models.ForeignKey(RecipeTemplate, related_name="grouptemplates")
    params = models.TextField(blank=True)
    priority = models.SmallIntegerField(default=0)
    role = models.ForeignKey(TaskRoleEnum, null=True, blank=True)

    def __unicode__(self):
        return self.group.name

    class Meta:
        ordering = ('priority',)


class GroupTestTemplate(ObjParams, models.Model):
    test = models.ForeignKey(Test)
    group = models.ForeignKey(GroupTemplate, related_name="grouptests")
    params = models.TextField(blank=True)
    priority = models.SmallIntegerField(default=0)
    role = models.ForeignKey(TaskRoleEnum, null=True, blank=True)

    def __unicode__(self):
        return self.test.name

    def get_role(self):
        if self.role:
            return self.role.name

    class Meta:
        ordering = ('priority',)


class TaskTemplate(ObjParams, models.Model):
    NONE, STANDALONE, CLIENTS, SERVERS, CLIENT, MASTER = 0, 1, 2, 3, 4, 5
    ROLE_ENUM = (
        (NONE, "None"),
        (STANDALONE, "STANDALONE"),
        (CLIENTS, "CLIENTS"),
        (SERVERS, "SERVERS"),
        (CLIENT, "CLIENT"),
        (MASTER, "MASTER"),
    )
    test = models.ForeignKey(Test)
    recipe = models.ForeignKey(RecipeTemplate, related_name="tasks")
    params = models.TextField(blank=True)
    priority = models.SmallIntegerField(default=0)
    role = models.ForeignKey(TaskRoleEnum, null=True, blank=True)

    def __unicode__(self):
        return self.test.name

    def get_role(self):
        if self.role:
            return self.role.name

    def set_role(self, value):
        if value in ["None", ""]:
            self.role = None
        else:
            self.role, status = TaskRoleEnum.objects.get_or_create(name=value)
        self.save()


class Job(models.Model):
    template = models.ForeignKey(JobTemplate)
    uid = models.CharField("Job ID", max_length=12, unique=True)
    date = TZDateTimeField(default=datetime.now)
    is_running = models.BooleanField(default=False)
    is_finished = models.BooleanField(default=False)  # this is for checking (no used for data from beaker)
    schedule = models.ForeignKey(TaskPeriodSchedule, null=True, blank=True)

    def __unicode__(self):
        return self.uid

    def to_json(self):
        return {
            'template_id': self.template.id,
            'uid': self.uid,
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'is_running' : self.is_running,
            'is_finished' : self.is_finished
        }

    def get_uid(self):
        return self.uid[2:]

    def get_url_beaker(self):
        return "%s/%s/" % (settings.BEAKER_SERVER, self.uid)


class Recipe(models.Model):
    UNKNOW = 0
    RUNNING = 1
    COMPLETED = 2
    WAITING = 3
    QUEUED = 4
    ABORTED = 5
    CANCELLED = 6
    NEW = 7
    SCHEDULED = 8
    PROCESSED = 9
    RESERVED = 10
    STATUS_CHOICES = (
        (UNKNOW, u"Unknow"),
        (NEW, u"New"),
        (SCHEDULED, u"Scheduled"),
        (RUNNING, u"Running"),
        (COMPLETED, u"Completed"),
        (WAITING, u"Waiting"),
        (QUEUED, u"Queued"),
        (ABORTED, u"Aborted"),
        (CANCELLED, u"Cancelled"),
        (PROCESSED, u"Processed"),
        (RESERVED, u"Reserved")
    )
    job = models.ForeignKey(Job, related_name="recipes")
    uid = models.CharField("Recipe ID", max_length=12, unique=True)
    whiteboard = models.CharField("Whiteboard", max_length=64)
    status = models.SmallIntegerField(choices=STATUS_CHOICES, default=UNKNOW)
    result = models.SmallIntegerField(choices=RESULT_CHOICES, default=UNKNOW)
    resultrate = models.FloatField(default= -1.)
    system = models.ForeignKey(System,)
    arch = models.ForeignKey(Arch,)
    distro = models.ForeignKey(Distro,)
    parentrecipe = models.ForeignKey("Recipe", null=True, blank=True)
    statusbyuser = models.SmallIntegerField(choices=USERSTATUS_CHOICES, default=NONE)

    def __unicode__(self):
        return self.uid

    def to_json(self):
        return {
            'uid': self.uid,
            'whiteboard': self.whiteboard,
            'result' : self.get_result_display(),
            'status' : self.get_status_display(),
            'resultrate': self.resultrate,
            'system': self.system.to_json(),
            'arch': self.arch.name,
            'distro': self.distro.name,
            'parentrecipe' : self.parentrecipe.to_json() if self.parentrecipe else None,
            'statusbyuser' : self.get_statusbyuser_display()
    }

    def get_template(self):
        return self.job.template

    def set_result(self, value):
        try:
            self.result = [it[0] for it in RESULT_CHOICES if it[1] == value.lower()][0]
        except IndexError:
            sys.stderr.write("IndexError: result %s %s %s" % (value, self.result, RESULT_CHOICES))

    def get_result(self):
        if self.statusbyuser == WAIVED: return [it[1] for it in USERSTATUS_CHOICES if it[0] == WAIVED][0]
        return [it[1] for it in RESULT_CHOICES if it[0] == self.result][0]

    def set_status(self, value):
        try:
            self.status = [it[0] for it in self.STATUS_CHOICES if it[1] == value][0]
        except IndexError:
            sys.stderr.write("IndexError: status %s %s %s" % (value, self.status, self.STATUS_CHOICES))

    def get_status(self):
        try:
            return [it[1] for it in self.STATUS_CHOICES if it[0] == self.status][0]
        except IndexError:
            return "uknow-%s" % self.status

    def set_waived(self):
        self.statusbyuser = WAIVED
        self.save()

    def recount_result(self):
        result = Task.objects.values('result', "statusbyuser").filter(recipe=self).annotate(Count('result')).order_by("uid")
        total, total_ok, waived = 0, 0, False
        running = None
        failed_test = []
        i = 0
        for it in Task.objects.filter(recipe=self).order_by("uid"):
            if i == 0 and it.result in [FAIL, WARN, ABOART]:
                self.result = FAILINSTALL
                # self.save()
            i += 1

            if it.result == PASS or it.statusbyuser == WAIVED:
                total_ok += 1
            total += 1

            if it.statusbyuser == WAIVED:
                waived = True

            if it.result in [WARN, FAIL] and it.statusbyuser != WAIVED:
                failed_test.append(it)

            if it.result == NEW and not running:
                running = it

        if waived:
            if failed_test:
                self.result = failed_test[0].result
            else:
                self.result = PASS
            if running and running.test.name == settings.RESERVE_TEST \
               and total_ok + 1 == total: self.set_waived()
        if total != 0:
            self.resultrate = total_ok * 100. / total
        else:
            self.resultrate = 0
        if waived and total_ok == total: self.set_waived()

    def get_date(self):
        return self.job.date

    def get_distro_label(self):
        dn = self.distro.name
        raw = dn.split("-")
        if len(raw) > 2:
            return "-".join(raw[:-1])
        else:
            return dn

    def get_dict(self):
        return {
            "arch": self.arch.name,
            "distro": self.distro.name,
            "distro_label": self.get_distro_label(),
            "whiteboard": self.whiteboard,
        }

    def is_running(self):
        # this makes about 1000 requests into DB, I think it is not necessary here.
        # self.recount_result()
        return self.status == self.RUNNING or self.status == self.RESERVED

    def get_info(self):
        # TODO: ???? Toto je asi blbost ????
        tests = Test.objects.filter(task__recipe=self, task__statusbyuser=NONE, task__result__in=[NEW, WARN, FAIL]).order_by("task__uid")[:1]
        return tests

    def is_result_pass(self):
        return (PASS == self.result)


class Task(models.Model):
    uid = models.CharField("Task ID", max_length=12, unique=True)
    recipe = models.ForeignKey(Recipe)
    test = models.ForeignKey(Test)
   # date = models.DateField(null=True, blank=True)
    result = models.SmallIntegerField(choices=RESULT_CHOICES, default=UNKNOW)
    status = models.SmallIntegerField(choices=Recipe.STATUS_CHOICES, default=UNKNOW)
    duration = models.FloatField(default= -1.)
    datestart = TZDateTimeField(null=True, blank=True)
    statusbyuser = models.SmallIntegerField(choices=USERSTATUS_CHOICES, default=NONE)
    alias = models.CharField(max_length=32, blank=True, null=True)
    # def __init__(self, *args, **kwargs):
    #    super(Task, self).__init__(*args, **kwargs)

    def __unicode__(self):
        return self.uid

    def to_json(self):
        return {
            'uid': self.uid,
            'recipe': self.recipe.uid,
            'test': self.test.to_json(),
            'datestart': self.datestart.strftime("%Y-%m-%d %H:%M:%S") if self.datestart else None,
            'result' : self.get_result_display(),
            'status' : self.get_status_display(),
            'statusbyuser': self.get_statusbyuser_display(),
            'duration': self.duration
        }

    def get_url_journal(self):  # , job=None, recipe=None):
        # if recipe == None: recipe = self.recipe
        # if job == None: job = recipe.job
        url = None
        return url % (self.uid[0:5], self.uid)

    def load_journal(self):

        url = self.get_url_journal()
        try:
            response = urllib2.urlopen(url)
            html = response.read()
        except urllib2.HTTPError, e:
            print url, ":", e.getcode()
            return None

        path_dir = "%sjournals/" % (settings.MEDIA_ROOT)
        path_file = "%s/%s-journal.xml" % (path_dir, self.uid)
        if not os.path.exists(path_dir): os.makedirs(path_dir)
        f = open(path_file, "w")
        f.write(html)
        f.close()

        if os.path.exists(path_file):
            return path_file

    def set_result(self, value):
        try:
            self.result = [it[0] for it in RESULT_CHOICES if it[1] == value.lower()][0]
        except IndexError:
            sys.stderr.write("IndexError: Task result %s %s %s" % (value, self.result, RESULT_CHOICES))

    def get_result(self):
        if self.statusbyuser == WAIVED: return [it[1] for it in USERSTATUS_CHOICES if it[0] == WAIVED][0]
        return [it[1] for it in RESULT_CHOICES if it[0] == self.result][0]


    def set_status(self, value):
        try:
            self.status = [it[0] for it in Recipe.STATUS_CHOICES if it[1].lower() == value.lower()][0]
        except IndexError:
            sys.stderr.write("IndexError: Task status %s %s %s" % (value, self.status, Recipe.STATUS_CHOICES))

    def is_completed(self):
        return (self.status == Recipe.COMPLETED)

    def set_waived(self):
        self.statusbyuser = WAIVED
        self.save()
        self.recipe.recount_result()
        self.recipe.save()


class PhaseLabel(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __unicode__(self):
        return self.name


class PhaseResult(models.Model):
    task = models.ForeignKey(Task)
    phase = models.ForeignKey(PhaseLabel)
    duration = models.FloatField()
    date = models.DateTimeField(null=True, blank=True)

    def __unicode__(self):
        return self.phase


class SkippedPhase(models.Model):
    id_task = models.IntegerField()
    id_phase = models.IntegerField()


class CheckProgress(models.Model):
    datestart = models.DateTimeField(default=currentDate())
    dateend = models.DateTimeField(null=True, blank=True)
    totalsum = models.IntegerField()
    actual = models.IntegerField(default=0)

    def __unicode__(self):
        return "%s" % self.datestart

    def counter(self):
        self.actual += 1
        self.save()

    def percent(self):
        if self.totalsum == 0:
            return None
        return int(self.actual * 100 / self.totalsum)

    def finished(self):
        self.dateend = currentDate()
        self.save()

    def get_duration(self):
        if self.dateend:
            return (self.dateend - self.datestart)
