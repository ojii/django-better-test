from setuptools import setup, find_packages


setup(
    name='django-better-test',
    version='0.9',
    description='A better test command for Django',
    url='https://github.com/ojii/django-better-test',
    author='Jonas Obrist',
    author_email='ojiidotch@gmail.com',
    license='BSD',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
    packages=find_packages(),
    install_requires=[
        'Django>=1.6',
    ],
)
