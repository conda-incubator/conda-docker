import subprocess


def pull(name, tag):
    subprocess.check_output(["docker", "pull", f"{name}:{tag}"])


def save(name, tag, filename):
    subprocess.check_output(["docker", "save", f"{name}:{tag}", "-o", filename])


def load(filename):
    subprocess.check_output(["docker", "load", "-i", filename])
