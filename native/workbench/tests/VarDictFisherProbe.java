import com.astrazeneca.vardict.data.fishertest.FisherExact;

/** Test-only probe of the unmodified release class; never shipped as a tool. */
public final class VarDictFisherProbe {
    public static void main(String[] args) {
        for (String argument : args) {
            String[] cells = argument.split(",");
            FisherExact test = new FisherExact(Integer.parseInt(cells[0]),
                Integer.parseInt(cells[1]), Integer.parseInt(cells[2]), Integer.parseInt(cells[3]));
            System.out.println(argument + "\t" + test.getPValue() + "\t" + test.getOddRatio());
        }
    }
}
