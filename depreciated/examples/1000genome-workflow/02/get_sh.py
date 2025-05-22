import yaml

tasks_info = {}
symlink_f = {'ALL.chr1.2500.vcf':'/qfs/projects/oddite/leeh736/git/1000genome-workflow/one_chr/ALL.chr1.2500.vcf',
        'ALL.chr1.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.2500.vcf':'/qfs/projects/oddite/leeh736/git/1000genome-workflow/one_chr/ALL.chr1.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.2500.vcf',
        'SAS': '/qfs/projects/oddite/leeh736/git/data/populations/SAS',
        'AFR': '/qfs/projects/oddite/leeh736/git/data/populations/AFR',
        'ALL': '/qfs/projects/oddite/leeh736/git/data/populations/ALL',
        'AMR': '/qfs/projects/oddite/leeh736/git/data/populations/AMR',
        'EAS': '/qfs/projects/oddite/leeh736/git/data/populations/EAS',
        'EUR': '/qfs/projects/oddite/leeh736/git/data/populations/EUR',
        'GBR': '/qfs/projects/oddite/leeh736/git/data/populations/GBR',
        }
with open("transformations.yml") as f:
    tasks = yaml.safe_load(f)
    for t in tasks['transformations']:
        tasks_info[t['name']] = t['sites'][0]['pfn']

def replace_args(args, syms=symlink_f):
    res = []
    for arg in args:
        if arg in syms:
            res.append('ln -s ' + syms[arg] + f' {arg}')
            res.append('ln -s /qfs/projects/oddite/leeh736/git/1000genome-workflow/data/20130502/columns.txt')
    return res

with open("workflow.yml") as f:
    data = yaml.safe_load(f)
    for idx, job in enumerate(data['jobs']):
        print(f"mkdir task_{idx};cd task_{idx};")
        print(";".join(replace_args(job['arguments'])))
        print(tasks_info[job['name']], ' '.join(job['arguments']))
        print(f"cd -")
