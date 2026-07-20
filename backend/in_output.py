# This subprogram allows to read the data files and transform them to 'float' format


def writer(filename, data_array):
    """function that writes the data specified by 'data_array' to 'filename' text file
    data_array should b a tuple of two arrays"""

    file1 = open(filename, "w")
    k = 0
    for data0 in data_array[0]:
        file1.write(str(data_array[0][k]) + "\t" + str(data_array[1][k]) + "\n")
        k += 1
    file1.close()


def reader(filename):
    """function that reads the data from 'filename' text file
    two columns of data should be separated by tabulation"""

    file1 = open(filename, "r")
    BUF = file1.readlines()
    file1.close()
    data0 = []
    data1 = []

    for buf in BUF:
        (EXPfb, EXPcb) = buf.split("\t")
        data0.append(float(EXPfb))
        data1.append(float(EXPcb))

    return (data0, data1)
