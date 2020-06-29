import os
import shutil
import filecmp
import tempfile

from django.core.files import File as django_file
from django.contrib.auth import get_user_model
from django.conf import settings

from rest_framework import status
from rest_framework.test import APITransactionTestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import Project, File, FileVersion
from .utils import testdata_path

User = get_user_model()


class QgisFileTestCase(APITransactionTestCase):

    def setUp(self):
        # Create a user
        self.user1 = User.objects.create_user(
            username='user1', password='abc123')
        self.user1.save()

        self.user2 = User.objects.create_user(
            username='user2', password='abc123')
        self.user2.save()

        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a project
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)
        self.project1.save()

    def tearDown(self):
        User.objects.all().delete()
        # Remove credentials
        self.client.credentials()
        Project.objects.all().delete()

    def test_push_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/files/{}/file.txt/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        self.assertTrue(File.objects.filter(original_path='file.txt').exists())

        file_obj = File.objects.get(original_path='file.txt')

        self.assertTrue(FileVersion.objects.filter(file=file_obj).exists())

        file_version_obj = FileVersion.objects.get(file=file_obj)

        file_version_obj_path = os.path.join(
            settings.PROJECTS_ROOT,
            file_version_obj.stored_file.name)

        self.assertTrue(filecmp.cmp(file_path, file_version_obj_path))

    def test_overwrite_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/files/{}/file.txt/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))
        # stored_file = os.path.join(str(self.project1.id), 'file.txt')
        updated_at1 = File.objects.get(original_path='file.txt').updated_at

        # Push again the file
        response = self.client.post(
            '/api/v1/files/{}/file.txt/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(File.objects.all()), 1)

        self.assertEqual(len(FileVersion.objects.all()), 2)

        updated_at2 = File.objects.get(original_path='file.txt').updated_at

        self.assertTrue(updated_at2 > updated_at1)

        self.assertNotEqual(
            FileVersion.objects.all()[0].stored_file.name,
            FileVersion.objects.all()[1].stored_file.name)

    def test_push_file_with_path(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/files/{}/foo/bar/file.txt/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        self.assertTrue(
            File.objects.filter(original_path='foo/bar/file.txt').exists())

    def test_push_file_with_unsafe_path(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/files/{}/../foo/bar/file.txt/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertEqual(response.status_code, 400)

    def test_push_file_invalid_project(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/files/{}/foo/bar/file.txt/?client=qgis'.format(
                '979bdbc8-448d-42f1-91c2-6dc80a836418'),  # Random uuid
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertTrue(response.status_code in [400, 403])

    def test_pull_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        # Pull the file
        response = self.client.get(
            '/api/v1/files/{}/file.txt/?client=qgis'.format(self.project1.id))

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'file.txt')
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path('file.txt')))

    def test_pull_file_with_path(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='foo/bar/file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(
                f,
                name=os.path.join(
                    'foo/bar',
                    os.path.basename(f.name))))

        # Pull the file
        response = self.client.get(
            '/api/v1/files/{}/foo/bar/file.txt/?client=qgis'.format(self.project1.id))

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'foo/bar/file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'foo/bar/file.txt')
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path('file.txt')))

    def test_list_files(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        f = open(testdata_path('file2.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file2.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        response = self.client.get(
            '/api/v1/files/{}/?client=qgis'.format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k['name'])

        self.assertEqual(json[0]['name'], 'file.txt')
        self.assertEqual(json[0]['size'], 13)
        self.assertEqual(json[1]['name'], 'file2.txt')
        self.assertEqual(json[1]['size'], 13)
        self.assertEqual(
            json[0]['sha256'],
            '8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d')
        self.assertEqual(
            json[1]['sha256'],
            'fcc85fb502bd772aa675a0263b5fa665bccd5d8d93349d1dbc9f0f6394dd37b9')

    def test_delete_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file.txt')

        file_version_obj = FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        file_path_on_server = os.path.join(
            settings.PROJECTS_ROOT,
            file_version_obj.stored_file.name
        )
        self.assertTrue(os.path.isfile(file_path_on_server))

        self.assertEqual(len(File.objects.all()), 1)
        self.assertEqual(len(FileVersion.objects.all()), 1)

        response = self.client.delete(
            '/api/v1/files/{}/file.txt/?client=qgis'.format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        self.assertEqual(len(File.objects.all()), 0)
        self.assertEqual(len(FileVersion.objects.all()), 0)
        self.assertFalse(os.path.isfile(file_path_on_server))

    def test_delete_file_with_path(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='foo/bar/file.txt')

        file_version_obj = FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        file_path_on_server = os.path.join(
            settings.PROJECTS_ROOT,
            file_version_obj.stored_file.name
        )
        self.assertTrue(os.path.isfile(file_path_on_server))

        self.assertEqual(len(File.objects.all()), 1)
        self.assertEqual(len(FileVersion.objects.all()), 1)

        response = self.client.delete(
            '/api/v1/files/{}/foo/bar/file.txt/?client=qgis'.format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        self.assertEqual(len(File.objects.all()), 0)
        self.assertEqual(len(FileVersion.objects.all()), 0)
        self.assertFalse(os.path.isfile(file_path_on_server))

    def test_file_history(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        f2 = open(testdata_path('file2.txt'))

        file_obj = File.objects.create(
            project=self.project1,
            original_path='foo/bar/file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)),
            uploaded_by=self.user1)

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f2, name=os.path.basename(f.name)),
            uploaded_by=self.user2)

        response = self.client.get(
            '/api/v1/files/{}/?client=qgis'.format(self.project1.id))

        self.assertTrue(status.is_success(response.status_code))

        versions = response.json()[0]['versions']

        self.assertEqual(len(versions), 2)
        self.assertTrue(
            versions[0]['created_at'] < versions[1]['created_at'])

        self.assertEqual(
            versions[0]['sha256'],
            '8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d')
        self.assertEqual(
            versions[1]['sha256'],
            'fcc85fb502bd772aa675a0263b5fa665bccd5d8d93349d1dbc9f0f6394dd37b9')

        self.assertEqual(versions[0]['size'], 13)
        self.assertEqual(versions[1]['size'], 13)

        self.assertEqual(versions[0]['uploaded_by'], 'user1')
        self.assertEqual(versions[1]['uploaded_by'], 'user2')

    def test_pull_file_version(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        f2 = open(testdata_path('file2.txt'))

        file_obj = File.objects.create(
            project=self.project1,
            original_path='foo/bar/file.txt')

        file_version_obj = FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)),
            uploaded_by=self.user1)

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f2, name=os.path.basename(f.name)),
            uploaded_by=self.user2)

        # Pull the last file
        response = self.client.get(
            '/api/v1/files/{}/foo/bar/file.txt/?client=qgis'.format(self.project1.id))

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'foo/bar/file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'foo/bar/file.txt')
        self.assertFalse(
            filecmp.cmp(temp_file.name, testdata_path('file.txt')))

        response = self.client.get(
            '/api/v1/files/{}/foo/bar/file.txt/'.format(self.project1.id),
            {
                "version": file_version_obj.created_at,
                "client": "qgis",
            },
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'foo/bar/file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'foo/bar/file.txt')
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path('file.txt')))

    def test_push_file_different_filename(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/files/{}/foo/bar/filezz.txt/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        self.assertTrue(
            File.objects.filter(original_path='foo/bar/filezz.txt').exists())

    def test_one_qgis_project_per_project(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        file_path = testdata_path('file.txt')

        # Push a QGIS project file
        response = self.client.post(
            '/api/v1/files/{}/foo/bar/file.qgs/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push again the same QGIS project file (this is allowed)
        response = self.client.post(
            '/api/v1/files/{}/foo/bar/file.qgs/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push another QGIS project file
        response = self.client.post(
            '/api/v1/files/{}/foo/bar/file2.qgs/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertEqual(response.status_code, 400)

        # Push another QGIS project file
        response = self.client.post(
            '/api/v1/files/{}/foo/bar/file2.qgz/?client=qgis'.format(self.project1.id),
            {
                "file": open(file_path, 'rb'),
            },
            format='multipart'
        )
        self.assertEqual(response.status_code, 400)

    def test_list_files_wrong_client(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        f = open(testdata_path('file.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        f = open(testdata_path('file2.txt'))
        file_obj = File.objects.create(
            project=self.project1,
            original_path='file2.txt')

        FileVersion.objects.create(
            file=file_obj,
            stored_file=django_file(f, name=os.path.basename(f.name)))

        response = self.client.get(
            '/api/v1/files/{}/?client=PDP8'.format(self.project1.id))
        self.assertFalse(status.is_success(response.status_code))