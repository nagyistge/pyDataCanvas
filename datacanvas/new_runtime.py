# -*- coding: utf-8 -*-

"""
A series of Runtime.
"""

import itertools
import functools
from datacanvas.clusters import EmrCluster, GenericHadoopCluster
from datacanvas.utils import *
from datacanvas.module import get_settings_from_file


class BasicRuntime(object):
    def __init__(self, spec_filename="spec.json"):
        self.settings = get_settings_from_file(spec_filename)

    def __repr__(self):
        return str(self.settings)

    @staticmethod
    def cmd(args, shell=False, verbose=True):
        if verbose:
            print("Execute External Command : '%s'" % args)
        ret = subprocess.call(args, shell=shell, env=os.environ.copy())
        if verbose:
            print("Exit with exit code = %d" % ret)
        return ret

    @staticmethod
    def exit(ret_code):
        sys.exit(ret_code)


def HadoopRuntime(*args, **kwargs):
    from warnings import warn
    warn("Use 'GenericHadoopRuntime' class! 'HadoopRuntime' is deprecated.")
    return GenericHadoopRuntime(*args, **kwargs)


class EmrRuntime(BasicRuntime):
    def __init__(self, spec_filename="spec.json"):
        super(EmrRuntime, self).__init__(spec_filename)
        self.grt = GenericHadoopRuntime()

    def get_s3_working_dir(self, path=""):
        return self.grt.get_working_dir(path)

    def get_emr_job_name(self):
        return self.grt.get_job_name()


class HiveRuntime(BasicRuntime):
    def __init__(self, spec_filename="spec.json"):
        super(HiveRuntime, self).__init__(spec_filename)
        self.grt = GenericHadoopRuntime()

    def execute(self, hive_script, generated_hive_script=None):
        return self.grt.execute_hive(hive_script)


class EmrHiveRuntime(BasicRuntime):
    def __init__(self, spec_filename="spec.json"):
        super(EmrHiveRuntime, self).__init__(spec_filename)
        self.grt = GenericHadoopRuntime()

    def execute(self, main_hive_script, generated_hive_script=None, dump_logfiles=None, dump_logfile_retry_count=1):
        return self.grt.execute_hive(main_hive_script,
                                     logfiles=dump_logfiles,
                                     retry_count=dump_logfile_retry_count)


class PigRuntime(BasicRuntime):
    def __init__(self, spec_filename="spec.json"):
        super(PigRuntime, self).__init__(spec_filename)
        self.grt = GenericHadoopRuntime()

    def execute(self, pig_script):
        self.grt.execute_pig(pig_script)


class EmrPigRuntime(BasicRuntime):
    def __init__(self, spec_filename="spec.json"):
        super(EmrPigRuntime, self).__init__(spec_filename)
        self.grt = GenericHadoopRuntime()

    def execute(self, pig_script, dump_logfiles=None, dump_logfile_retry_count=1):
        return self.grt.execute_pig(pig_script,
                                    logfiles=dump_logfiles,
                                    retry_count=dump_logfile_retry_count)


class ScriptBuilder(object):

    def __init__(self, settings, s3_working_root, hdfs_working_root):
        self.settings = settings
        self.s3_working_root = s3_working_root
        self.hdfs_working_root = hdfs_working_root

    def get_hdfs_working_dir(self, dir_path=""):
        return s3join(self.hdfs_working_root, dir_path)

    def get_s3_working_dir(self, dir_path=""):
        return s3join(self.s3_working_root, dir_path)


class HiveScriptBuilder(ScriptBuilder):

    def __init__(self, settings, s3_working_root, hdfs_working_root):
        super(HiveScriptBuilder, self).__init__(settings, s3_working_root, hdfs_working_root)

    def get_hive_namespace(self):
        ps = self.settings
        glb_vars = ps.GlobalParam
        return "zetjobns_{userName}_job{job_id}_blk{blk_id}".format(
            userName=glb_vars['userName'],
            job_id=glb_vars['jobId'],
            blk_id=glb_vars['blockId'])

    def get_hive_table(self, output_name):
        ps = self.settings
        glb_vars = ps.GlobalParam
        return "zetjob_{userName}_job{job_id}_blk{blk_id}_OUTPUT_{output_name}".format(
            userName=glb_vars['userName'],
            job_id=glb_vars['jobId'],
            blk_id=glb_vars['blockId'],
            output_name=output_name)

    def hive_output_builder(self, output_name, output_obj):
        out_type = output_obj.types[0]
        if out_type.startswith("hive.table"):
            return self.get_hive_table(output_name)
        elif out_type.startswith("hive.hdfs"):
            return self.get_hdfs_working_dir("OUTPUT_%s" % output_name)
        elif out_type.startswith("hive.s3"):
            return self.get_s3_working_dir("OUTPUT_%s" % output_name)
        else:
            raise ValueError("Invalid type for hive, type must start with 'hive.table' or 'hive.hdfs' or 'hive.s3'")

    def header_builder(self, hive_ns, uploaded_files, uploaded_jars):
        # Build Output Tables
        for output_name, output_obj in self.settings.Output._asdict().items():
            output_obj.val = self.hive_output_builder(output_name, output_obj)

        return "\n".join(
            itertools.chain(
                ["ADD FILE %s;" % f for f in uploaded_files],
                ["ADD JAR %s;" % f for f in uploaded_jars],
                ["set hivevar:MYNS = %s;" % hive_ns],
                ["set hivevar:PARAM_%s = %s;" % (k, v) for k, v in self.settings.Param._asdict().items() if v.is_primitive],
                ["set hivevar:INPUT_%s = %s;" % (k, v.val) for k, v in self.settings.Input._asdict().items()],
                ["set hivevar:OUTPUT_%s = %s;" % (k, v.val) for k, v in self.settings.Output._asdict().items()]))

    def generate_script(self, hive_script, uploaded_files, uploaded_jars):
        hive_ns = self.get_hive_namespace()

        # Build Input, Output and Param
        header = self.header_builder(hive_ns, uploaded_files, uploaded_jars)

        import tempfile
        tmp_file = tempfile.NamedTemporaryFile(prefix="hive_generated_", suffix=".hql", delete=False)
        tmp_file.close()
        target_filename = tmp_file.name

        with open(hive_script, "r") as f, open(target_filename, "w+") as out_f:
            out_f.write("--------------------------\n")
            out_f.write("-- Header\n")
            out_f.write("--------------------------\n")
            out_f.write(header)
            out_f.write("\n")
            out_f.write("--------------------------\n")
            out_f.write("-- Main\n")
            out_f.write("--------------------------\n")
            out_f.write("\n")
            out_f.write(f.read())

        return target_filename


class PigScriptBuilder(ScriptBuilder):

    def __init__(self, settings, s3_working_root, hdfs_working_root):
        super(PigScriptBuilder, self).__init__(settings, s3_working_root, hdfs_working_root)

    def pig_output_builder(self, output_name, output_obj):
        out_type = output_obj.types[0]
        if out_type.startswith("hdfs"):
            return self.get_hdfs_working_dir("OUTPUT_%s" % output_name)
        elif out_type.startswith("s3"):
            return self.get_s3_working_dir("OUTPUT_%s" % output_name)
        else:
            raise ValueError("Invalid type for hive, type must start with 'hive.table' or 'hive.hdfs' or 'hive.s3'")

    def header_builder(self, uploaded_jars):
        # Build Output Tables
        for output_name, output_obj in self.settings.Output._asdict().items():
            output_obj.val = self.pig_output_builder(output_name, output_obj)

        return "\n".join(
            itertools.chain(
                ["%%declare PARAM_%s '%s'" % (k, v)
                 for k, v in self.settings.Param._asdict().items()
                 if v.is_primitive],
                ["%%declare INPUT_%s '%s'" % (k, v.val)
                 for k, v in self.settings.Input._asdict().items()],
                ["%%declare OUTPUT_%s '%s'" % (k, v.val)
                 for k, v in self.settings.Output._asdict().items()],
                ["REGISTER '%s';" % f
                 for f in uploaded_jars]
            ))

    def generate_script(self, pig_script, uploaded_jars):

        # Build Input, Output and Param
        header = self.header_builder(uploaded_jars)

        import tempfile
        tmp_file = tempfile.NamedTemporaryFile(prefix="pig_generated_", suffix=".pig", delete=False)
        tmp_file.close()
        target_filename = tmp_file.name

        with open(pig_script, "r") as f, open(target_filename, "w+") as out_f:
            out_f.write("/*************************\n")
            out_f.write(" * Header\n")
            out_f.write(" *************************/\n")
            out_f.write(header)
            out_f.write("\n")
            out_f.write("/*************************\n")
            out_f.write(" * Main\n")
            out_f.write(" *************************/\n")
            out_f.write("\n")
            out_f.write(f.read())
            out_f.write("\n")

        return target_filename


class GenericHadoopRuntime(BasicRuntime):

    def __init__(self, cluster_var_name="cluster"):
        super(GenericHadoopRuntime, self).__init__()
        self.hadoop_type = None
        self.cluster = None
        self.working_root = None
        self.hdfs_working_root = None
        self.s3_working_root = None
        self.global_params = self.settings.GlobalParam
        self.cluster_params = None

        param_dict = self.settings.Param._asdict()
        if param_dict.has_key(cluster_var_name) and param_dict.get(cluster_var_name).is_cluster:
            cluster_type = self._get_cluster_type(cluster_var_name)
            print param_dict.get(cluster_var_name).type
            print "=================================================="
            print "Use cluster var :: '%s'" % cluster_var_name
            print "           type :: '%s'" % cluster_type
            print "=================================================="
            self.switch_hadoop_env(cluster_type, cluster_var_name)

    def _get_cluster_type(self, cluster_var_name):
        cparam = self.settings.Param._asdict().get(cluster_var_name).val
        return cparam["Type"]

    def _get_cluster_params(self, cluster_var_name):
        cparam = self.settings.Param._asdict().get(cluster_var_name).val
        cluster_params = {p["Name"]: p.get("Val", None) for p in cparam["Parameters"]}
        return cluster_params

    def switch_hadoop_env(self, hadoop_type, cluster_var_name="cluster", extra_env_vars=None):
        print "Switch to Hadoop type = '%s'" % hadoop_type
        cluster_params = self._get_cluster_params(cluster_var_name)
        self.cluster_params = cluster_params

        if hadoop_type in ["EMR", "EMR_SPOT"]:
            self.hadoop_type = hadoop_type
            self.cluster = EmrCluster(aws_region=cluster_params["region"],
                                      aws_key=cluster_params["accessKey"],
                                      aws_secret=cluster_params["accessSecret"],
                                      jobflow_id=cluster_params["jobFlowId"])
            self.cluster.prepare(hadoop_type, **cluster_params)
            self.working_root = self.cluster.get_working_root(cluster_params, self.global_params)
            self.s3_working_root = self.working_root
            self.hdfs_working_root = "/"
        elif hadoop_type in ["CDH4", "CDH5"]:
            self.hadoop_type = hadoop_type
            self.cluster = GenericHadoopCluster(**cluster_params)
            self.cluster.prepare(hadoop_type, **cluster_params)
            self.working_root = self.cluster.get_working_root(cluster_params, self.global_params)
            self.s3_working_root = None
            self.hdfs_working_root = cluster_params["hdfs_root"]
        else:
            # if hadoop_type in ["CDH4", "CDH5"]:
            raise Exception("Do NOT support hadoop_type '%s'" % hadoop_type)

        self.cluster.clean_working_dir(self.working_root)
        print self.working_root

    def get_working_dir(self, path=""):
        if not self.working_root:
            raise ValueError("Did NOT define 'working_root'!")

        return s3join(self.working_root, path)

    def get_job_name(self):
        ps = self.settings
        glb_vars = ps.GlobalParam
        return os.path.join('zetjob', glb_vars['userName'],
                            "job%s" % glb_vars['jobId'], "blk%s" % glb_vars['blockId'])

    def execute_jar(self, jar_path, jar_args, main_class="", *args, **kwargs):
        job_name = self.get_job_name()

        remote_jar_path = self.cluster.prepare_working_file(self.working_root, jar_path)
        return self.cluster.execute_jar(job_name=job_name, jar_path=remote_jar_path,
                                        jar_args=jar_args, main_class=main_class,
                                        *args, **kwargs)

    def execute_hive(self, hive_main, *args, **kwargs):
        job_name = self.get_job_name()

        hb = HiveScriptBuilder(self.settings,
                               s3_working_root=self.s3_working_root,
                               hdfs_working_root=self.hdfs_working_root)
        generated_hql = hb.generate_script(hive_main, [], [])
        remote_hive_script = self.cluster.prepare_working_file(self.working_root, generated_hql)
        return self.cluster.execute_hive(job_name=job_name,
                                         hive_script=remote_hive_script,
                                         *args, **kwargs)

    def execute_pig(self, pig_main, *args, **kwargs):
        job_name = self.get_job_name()

        pb = PigScriptBuilder(self.settings,
                              s3_working_root=self.s3_working_root,
                              hdfs_working_root=self.hdfs_working_root)
        generated_pig = pb.generate_script(pig_main, [])
        remote_pig_script = self.cluster.prepare_working_file(self.working_root, generated_pig)
        return self.cluster.execute_pig(job_name=job_name,
                                        pig_script=remote_pig_script,
                                        *args, **kwargs)


##############
# Decorators #
##############

class DataCanvas(object):
    """DataCanvas"""

    def __init__(self, name):
        self._name = name
        self._graph = []
        self._rt = None

    def basic_runtime(self, spec_json="spec.json"):
        def decorator(method):
            rt = BasicRuntime(spec_filename=spec_json)
            params = rt.settings.Param
            inputs = rt.settings.Input
            outputs = rt.settings.Output

            @functools.wraps(method)
            def wrapper(_rt=rt, _params=params, _inputs=inputs, _outputs=outputs):
                print rt
                method(_rt, _params, _inputs, _outputs)

            self._graph.append(wrapper)
            return wrapper

        return decorator

    def hadoop_runtime(self, spec_json="spec.json"):
        def decorator(method):
            rt = GenericHadoopRuntime(cluster_var_name="cluster")
            params = rt.settings.Param
            inputs = rt.settings.Input
            outputs = rt.settings.Output

            @functools.wraps(method)
            def wrapper(_rt=rt, _params=params, _inputs=inputs, _outputs=outputs):
                print rt
                method(_rt, _params, _inputs, _outputs)

            self._graph.append(wrapper)
            return wrapper

        return decorator

    def run(self):
        for m in self._graph:
            m()