# Copyright 2010 Google Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

import boto
from boto import handler
from boto.resultset import ResultSet
from boto.exception import InvalidAclError
from boto.gs.acl import ACL, CannedACLStrings
from boto.gs.acl import SupportedPermissions as GSPermissions
from boto.gs.bucketlistresultset import VersionedBucketListResultSet
from boto.gs.cors import Cors
from boto.gs.key import Key as GSKey
from boto.s3.acl import Policy
from boto.s3.bucket import Bucket as S3Bucket
import xml.sax

# constants for http query args
DEF_OBJ_ACL = 'defaultObjectAcl'
STANDARD_ACL = 'acl'
CORS_ARG = 'cors'

class Bucket(S3Bucket):
    VersioningBody = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                      '<VersioningConfiguration><Status>%s</Status>'
                      '</VersioningConfiguration>')
    WebsiteBody = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<WebsiteConfiguration>%s%s</WebsiteConfiguration>')
    WebsiteMainPageFragment = '<MainPageSuffix>%s</MainPageSuffix>'
    WebsiteErrorFragment = '<NotFoundPage>%s</NotFoundPage>'

    def __init__(self, connection=None, name=None, key_class=GSKey):
        super(Bucket, self).__init__(connection, name, key_class)

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == 'Name':
            self.name = value
        elif name == 'CreationDate':
            self.creation_date = value
        else:
            setattr(self, name, value)

    def get_key(self, key_name, headers=None, version_id=None,
                response_headers=None, generation=None):
        """
        Check to see if a particular key exists within the bucket.  This
        method uses a HEAD request to check for the existance of the key.
        Returns: An instance of a Key object or None

        :type key_name: string
        :param key_name: The name of the key to retrieve

        :type response_headers: dict
        :param response_headers: A dictionary containing HTTP
            headers/values that will override any headers associated
            with the stored object in the response.  See
            http://goo.gl/06N3b for details.

        :rtype: :class:`boto.s3.key.Key`
        :returns: A Key object from this bucket.
        """
        query_args_l = []
        if generation:
            query_args_l.append('generation=%s' % generation)
        if response_headers:
            for rk, rv in response_headers.iteritems():
                query_args_l.append('%s=%s' % (rk, urllib.quote(rv)))

        key, resp = self._get_key_internal(key_name, headers,
                                           query_args_l=query_args_l)
        return key

    def copy_key(self, new_key_name, src_bucket_name, src_key_name,
                 metadata=None, src_version_id=None, storage_class='STANDARD',
                 preserve_acl=False, encrypt_key=False, headers=None,
                 query_args=None, src_generation=None):
        if src_generation:
            if headers is None:
                headers = {}
            headers['x-goog-copy-source-generation'] = src_generation
        super(Bucket, self).copy_key(new_key_name, src_bucket_name,
                                     src_key_name, metadata=metadata,
                                     storage_class=storage_class,
                                     preserve_acl=preserve_acl,
                                     encrypt_key=encrypt_key, headers=headers,
                                     query_args=query_args)

    def list_versions(self, prefix='', delimiter='', marker='',
                      generation_marker='', headers=None):
        """
        List versioned objects within a bucket.  This returns an
        instance of an VersionedBucketListResultSet that automatically
        handles all of the result paging, etc. from GCS.  You just need
        to keep iterating until there are no more results.  Called
        with no arguments, this will return an iterator object across
        all keys within the bucket.

        :type prefix: string
        :param prefix: allows you to limit the listing to a particular
            prefix.  For example, if you call the method with
            prefix='/foo/' then the iterator will only cycle through
            the keys that begin with the string '/foo/'.

        :type delimiter: string
        :param delimiter: can be used in conjunction with the prefix
            to allow you to organize and browse your keys
            hierarchically. See:
            https://developers.google.com/storage/docs/reference-headers#delimiter
            for more details.

        :type marker: string
        :param marker: The "marker" of where you are in the result set

        :type generation_marker: string
        :param marker: The "generation marker" of where you are in the result
            set

        :rtype:
            :class:`boto.gs.bucketlistresultset.VersionedBucketListResultSet`
        :return: an instance of a BucketListResultSet that handles paging, etc
        """
        return VersionedBucketListResultSet(self, prefix, delimiter,
                                            marker, generation_marker,
                                            headers)

    def delete_key(self, key_name, headers=None, version_id=None,
                   mfa_token=None, generation=None):
        query_args_l = []
        if generation:
            query_args_l.append('generation=%s' % generation)
        self._delete_key_internal(key_name, headers=headers,
                                  version_id=version_id, mfa_token=mfa_token,
                                  query_args_l=query_args_l)

    def set_acl(self, acl_or_str, key_name='', headers=None, version_id=None,
                generation=None):
        """Sets or changes a bucket's or key's ACL. The generation argument can
        be used to specify an object version, else we will modify the current
        version."""
        key_name = key_name or ''
        query_args = STANDARD_ACL
        if generation:
          query_args += '&generation=%s' % str(generation)
        if isinstance(acl_or_str, Policy):
            raise InvalidAclError('Attempt to set S3 Policy on GS ACL')
        elif isinstance(acl_or_str, ACL):
            self.set_xml_acl(acl_or_str.to_xml(), key_name, headers=headers,
                             query_args=query_args)
        else:
            self.set_canned_acl(acl_or_str, key_name, headers=headers,
                                generation=generation)

    def set_def_acl(self, acl_or_str, key_name='', headers=None):
        """sets or changes a bucket's default object acl. The key_name argument
        is ignored since keys have no default ACL property."""
        if isinstance(acl_or_str, Policy):
            raise InvalidAclError('Attempt to set S3 Policy on GS ACL')
        elif isinstance(acl_or_str, ACL):
            self.set_def_xml_acl(acl_or_str.to_xml(), '', headers=headers)
        else:
            self.set_def_canned_acl(acl_or_str, '', headers=headers)

    def get_acl_helper(self, key_name, headers, query_args):
        """provides common functionality for get_acl() and get_def_acl()"""
        response = self.connection.make_request('GET', self.name, key_name,
                                                query_args=query_args,
                                                headers=headers)
        body = response.read()
        if response.status == 200:
            acl = ACL(self)
            h = handler.XmlHandler(acl, self)
            xml.sax.parseString(body, h)
            return acl
        else:
            raise self.connection.provider.storage_response_error(
                response.status, response.reason, body)

    def get_acl(self, key_name='', headers=None, version_id=None,
                generation=None):
        """returns a bucket's acl. We include a version_id argument
           to support a polymorphic interface for callers, however,
           version_id is not relevant for Google Cloud Storage buckets
           and is therefore ignored here."""
        query_args = STANDARD_ACL
        if generation:
            query_args += '&generation=%s' % str(generation)
        return self.get_acl_helper(key_name, headers, query_args)

    def get_def_acl(self, key_name='', headers=None):
        """returns a bucket's default object acl. The key_name argument is
        ignored since keys have no default ACL property."""
        return self.get_acl_helper('', headers, DEF_OBJ_ACL)

    def set_canned_acl_helper(self, acl_str, key_name, headers, query_args):
        """provides common functionality for set_canned_acl() and
           set_def_canned_acl()"""
        assert acl_str in CannedACLStrings

        if headers:
            headers[self.connection.provider.acl_header] = acl_str
        else:
            headers={self.connection.provider.acl_header: acl_str}

        response = self.connection.make_request('PUT', self.name, key_name,
                headers=headers, query_args=query_args)
        body = response.read()
        if response.status != 200:
            raise self.connection.provider.storage_response_error(
                response.status, response.reason, body)

    def set_canned_acl(self, acl_str, key_name='', headers=None,
                       version_id=None, generation=None):
        """sets or changes a bucket's acl to a predefined (canned) value.
           We include a version_id argument to support a polymorphic
           interface for callers, however, version_id is not relevant for
           Google Cloud Storage buckets and is therefore ignored here."""
        query_args = STANDARD_ACL
        if generation:
            query_args += '&generation=%s' % str(generation)
        return self.set_canned_acl_helper(acl_str, key_name, headers,
                                          query_args=query_args)

    def set_def_canned_acl(self, acl_str, key_name='', headers=None):
        """sets or changes a bucket's default object acl to a predefined
           (canned) value. The key_name argument is ignored since keys have no
           default ACL property."""
        return self.set_canned_acl_helper(acl_str, '', headers,
                                          query_args=DEF_OBJ_ACL)

    def set_def_xml_acl(self, acl_str, key_name='', headers=None):
        """sets or changes a bucket's default object ACL. The key_name argument
        is ignored since keys have no default ACL property."""
        return self.set_xml_acl(acl_str, '', headers,
                                query_args=DEF_OBJ_ACL)

    def get_cors(self, headers=None):
        """returns a bucket's CORS XML"""
        response = self.connection.make_request('GET', self.name,
                                                query_args=CORS_ARG,
                                                headers=headers)
        body = response.read()
        if response.status == 200:
            # Success - parse XML and return Cors object.
            cors = Cors()
            h = handler.XmlHandler(cors, self)
            xml.sax.parseString(body, h)
            return cors
        else:
            raise self.connection.provider.storage_response_error(
                response.status, response.reason, body)

    def set_cors(self, cors, headers=None):
        """sets or changes a bucket's CORS XML."""
        cors_xml = cors.encode('UTF-8')
        response = self.connection.make_request('PUT', self.name,
                                                data=cors_xml,
                                                query_args=CORS_ARG,
                                                headers=headers)
        body = response.read()
        if response.status != 200:
            raise self.connection.provider.storage_response_error(
                response.status, response.reason, body)

    def get_storage_class(self):
        """
        Returns the StorageClass for the bucket.

        :rtype: str
        :return: The StorageClass for the bucket.
        """
        response = self.connection.make_request('GET', self.name,
                                                query_args='storageClass')
        body = response.read()
        if response.status == 200:
            rs = ResultSet(self)
            h = handler.XmlHandler(rs, self)
            xml.sax.parseString(body, h)
            return rs.StorageClass
        else:
            raise self.connection.provider.storage_response_error(
                response.status, response.reason, body)


    # Method with same signature as boto.s3.bucket.Bucket.add_email_grant(),
    # to allow polymorphic treatment at application layer.
    def add_email_grant(self, permission, email_address,
                        recursive=False, headers=None):
        """
        Convenience method that provides a quick way to add an email grant
        to a bucket. This method retrieves the current ACL, creates a new
        grant based on the parameters passed in, adds that grant to the ACL
        and then PUT's the new ACL back to GCS.

        :type permission: string
        :param permission: The permission being granted. Should be one of:
                           (READ, WRITE, FULL_CONTROL).

        :type email_address: string
        :param email_address: The email address associated with the GS
                              account your are granting the permission to.

        :type recursive: boolean
        :param recursive: A boolean value to controls whether the call
                          will apply the grant to all keys within the bucket
                          or not.  The default value is False.  By passing a
                          True value, the call will iterate through all keys
                          in the bucket and apply the same grant to each key.
                          CAUTION: If you have a lot of keys, this could take
                          a long time!
        """
        if permission not in GSPermissions:
            raise self.connection.provider.storage_permissions_error(
                'Unknown Permission: %s' % permission)
        acl = self.get_acl(headers=headers)
        acl.add_email_grant(permission, email_address)
        self.set_acl(acl, headers=headers)
        if recursive:
            for key in self:
                key.add_email_grant(permission, email_address, headers=headers)

    # Method with same signature as boto.s3.bucket.Bucket.add_user_grant(),
    # to allow polymorphic treatment at application layer.
    def add_user_grant(self, permission, user_id, recursive=False, headers=None):
        """
        Convenience method that provides a quick way to add a canonical user
        grant to a bucket. This method retrieves the current ACL, creates a new
        grant based on the parameters passed in, adds that grant to the ACL and
        then PUTs the new ACL back to GCS.

        :type permission: string
        :param permission:  The permission being granted.  Should be one of:
                            (READ|WRITE|FULL_CONTROL)

        :type user_id: string
        :param user_id:     The canonical user id associated with the GS account
                            you are granting the permission to.

        :type recursive: bool
        :param recursive: A boolean value to controls whether the call
                          will apply the grant to all keys within the bucket
                          or not.  The default value is False.  By passing a
                          True value, the call will iterate through all keys
                          in the bucket and apply the same grant to each key.
                          CAUTION: If you have a lot of keys, this could take
                          a long time!
        """
        if permission not in GSPermissions:
            raise self.connection.provider.storage_permissions_error(
                'Unknown Permission: %s' % permission)
        acl = self.get_acl(headers=headers)
        acl.add_user_grant(permission, user_id)
        self.set_acl(acl, headers=headers)
        if recursive:
            for key in self:
                key.add_user_grant(permission, user_id, headers=headers)

    def add_group_email_grant(self, permission, email_address, recursive=False,
                              headers=None):
        """
        Convenience method that provides a quick way to add an email group
        grant to a bucket. This method retrieves the current ACL, creates a new
        grant based on the parameters passed in, adds that grant to the ACL and
        then PUT's the new ACL back to GCS.

        :type permission: string
        :param permission: The permission being granted. Should be one of:
            READ|WRITE|FULL_CONTROL
            See http://code.google.com/apis/storage/docs/developer-guide.html#authorization
            for more details on permissions.

        :type email_address: string
        :param email_address: The email address associated with the Google
            Group to which you are granting the permission.

        :type recursive: bool
        :param recursive: A boolean value to controls whether the call
                          will apply the grant to all keys within the bucket
                          or not.  The default value is False.  By passing a
                          True value, the call will iterate through all keys
                          in the bucket and apply the same grant to each key.
                          CAUTION: If you have a lot of keys, this could take
                          a long time!
        """
        if permission not in GSPermissions:
            raise self.connection.provider.storage_permissions_error(
                'Unknown Permission: %s' % permission)
        acl = self.get_acl(headers=headers)
        acl.add_group_email_grant(permission, email_address)
        self.set_acl(acl, headers=headers)
        if recursive:
            for key in self:
                key.add_group_email_grant(permission, email_address,
                                          headers=headers)

    # Method with same input signature as boto.s3.bucket.Bucket.list_grants()
    # (but returning different object type), to allow polymorphic treatment
    # at application layer.
    def list_grants(self, headers=None):
        acl = self.get_acl(headers=headers)
        return acl.entries

    def disable_logging(self, headers=None):
        xml_str = '<?xml version="1.0" encoding="UTF-8"?><Logging/>'
        self.set_subresource('logging', xml_str, headers=headers)

    def enable_logging(self, target_bucket, target_prefix=None, headers=None):
        if isinstance(target_bucket, Bucket):
            target_bucket = target_bucket.name
        xml_str = '<?xml version="1.0" encoding="UTF-8"?><Logging>'
        xml_str = (xml_str + '<LogBucket>%s</LogBucket>' % target_bucket)
        if target_prefix:
            xml_str = (xml_str +
                       '<LogObjectPrefix>%s</LogObjectPrefix>' % target_prefix)
        xml_str = xml_str + '</Logging>'

        self.set_subresource('logging', xml_str, headers=headers)

    def configure_website(self, main_page_suffix=None, error_key=None,
                          headers=None):
        """
        Configure this bucket to act as a website

        :type suffix: str
        :param suffix: Suffix that is appended to a request that is for a
                       "directory" on the website endpoint (e.g. if the suffix
                       is index.html and you make a request to
                       samplebucket/images/ the data that is returned will
                       be for the object with the key name images/index.html).
                       The suffix must not be empty and must not include a
                       slash character. This parameter is optional and the
                       property is disabled if excluded.


        :type error_key: str
        :param error_key: The object key name to use when a 400
                          error occurs. This parameter is optional and the
                          property is disabled if excluded.

        """
        if main_page_suffix:
            main_page_frag = self.WebsiteMainPageFragment % main_page_suffix
        else:
            main_page_frag = ''

        if error_key:
            error_frag = self.WebsiteErrorFragment % error_key
        else:
            error_frag = ''

        body = self.WebsiteBody % (main_page_frag, error_frag)
        response = self.connection.make_request('PUT', self.name, data=body,
                                                query_args='websiteConfig',
                                                headers=headers)
        body = response.read()
        if response.status == 200:
            return True
        else:
            raise self.connection.provider.storage_response_error(
                response.status, response.reason, body)

    def get_website_configuration(self, headers=None):
        """
        Returns the current status of website configuration on the bucket.

        :rtype: dict
        :returns: A dictionary containing a Python representation
                  of the XML response from GCS. The overall structure is:

        * WebsiteConfiguration
          * MainPageSuffix: suffix that is appended to request that
              is for a "directory" on the website endpoint
          * NotFoundPage: name of an object to serve when site visitors
              encounter a 404
        """
        return self.get_website_configuration_xml(self, headers)[0]

    def get_website_configuration_with_xml(self, headers=None):
        """
        Returns the current status of website configuration on the bucket as
        unparsed XML.

        :rtype: 2-Tuple
        :returns: 2-tuple containing:
        1) A dictionary containing a Python representation
                  of the XML response from GCS. The overall structure is:
          * WebsiteConfiguration
            * MainPageSuffix: suffix that is appended to request that
                is for a "directory" on the website endpoint
            * NotFoundPage: name of an object to serve when site visitors
                encounter a 404
        2) unparsed XML describing the bucket's website configuration.
        """
        response = self.connection.make_request('GET', self.name,
                query_args='websiteConfig', headers=headers)
        body = response.read()
        boto.log.debug(body)

        if response.status != 200:
            raise self.connection.provider.storage_response_error(
                response.status, response.reason, body)

        e = boto.jsonresponse.Element()
        h = boto.jsonresponse.XmlHandler(e, None)
        h.parse(body)
        return e, body

    def delete_website_configuration(self, headers=None):
        self.configure_website(headers=headers)

    def get_versioning_status(self, headers=None):
        """
        Returns the current status of versioning configuration on the bucket.

        :rtype: boolean
        :returns: boolean indicating whether or not versioning is enabled.
        """
        response = self.connection.make_request('GET', self.name,
                                                query_args='versioning',
                                                headers=headers)
        body = response.read()
        boto.log.debug(body)
        if response.status != 200:
            raise self.connection.provider.storage_response_error(
                    response.status, response.reason, body)
        resp_json = boto.jsonresponse.Element()
        boto.jsonresponse.XmlHandler(resp_json, None).parse(body)
        resp_json = resp_json['VersioningConfiguration']
        return ('Status' in resp_json) and (resp_json['Status'] == 'Enabled')

    def configure_versioning(self, enabled, headers=None):
        if enabled == True:
            req_body = self.VersioningBody % ('Enabled')
        else:
            req_body = self.VersioningBody % ('Suspended')
        self.set_subresource('versioning', req_body, headers=headers)
